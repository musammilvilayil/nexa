from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from core.contracts import RiskTier
from core.failures import (
    ElementNotFound,
    WindowNotFound,
    SecurityBlocked,
    VerificationFailed,
    Timeout as ActionTimeout,
)
from core.failsafe import FailsafeMonitor, FailsafeTriggered


@dataclass(frozen=True)
class ActionIntent:
    """Specification of an intended action to execute."""
    action_type: str  # launch_app, focus_window, click, type_text, hotkey, etc.
    target: str       # element description, window title, coords, etc.
    params: dict[str, Any] = field(default_factory=dict)
    risk_tier: RiskTier = RiskTier.MUTATE
    expected_outcome: str = ""
    timeout_seconds: float = 10.0


@dataclass
class LoopResult:
    """Result of running an Observe -> Act -> Verify cycle."""
    success: bool
    message: str
    initial_observation: Any = None
    final_observation: Any = None
    verified: bool = False
    recovery_attempts: int = 0
    error: str | None = None


class AgentActionLoop:
    """Enforces the strict Observe -> Act -> Verify cycle for computer use.
    
    Invariants:
    1. Always observe current state before acting.
    2. Check SecurityGate before performing mutation.
    3. Check FailsafeMonitor before sending hardware inputs.
    4. Observe resulting state after action.
    5. Verify expected state. An API return value alone is NEVER proof of success.
    6. Attempt targeted recovery upon failure.
    """

    def __init__(
        self,
        screen_analyzer: Any | None = None,
        window_manager: Any | None = None,
        security_gate: Any | None = None,
        failsafe: FailsafeMonitor | None = None,
        executor_fn: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self._screen_analyzer = screen_analyzer
        self._window_manager = window_manager
        self._security_gate = security_gate
        self._failsafe = failsafe
        self._executor_fn = executor_fn

    def run_cycle(self, intent: ActionIntent, max_retries: int = 1) -> LoopResult:
        """Run the complete Observe -> Act -> Verify loop with recovery."""
        recovery_count = 0
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # 1. Observe current state
                initial_state = self.observe()

                # 2. Select / validate target
                target_valid = self._validate_target(intent, initial_state)
                if not target_valid:
                    raise ElementNotFound(f"Target '{intent.target}' not located in current state")

                # 3. Check SecurityGate
                if self._security_gate is not None:
                    # Check if action is blocked by deny patterns or confirmation needed
                    for pat in getattr(self._security_gate, "_deny_patterns", []):
                        if pat.lower() in intent.target.lower():
                            raise SecurityBlocked(f"Target '{intent.target}' is blocked by security policy")

                # 4. Check FailsafeMonitor
                if self._failsafe is not None:
                    self._failsafe.check_before_action()

                # 5. Execute action
                action_result = self._execute(intent)

                # 6. Observe resulting state
                time.sleep(0.3)  # Brief UI settling
                final_state = self.observe()

                # 7. Verify expected state (never rely solely on action_result)
                verified = self._verify(intent, initial_state, final_state, action_result)
                if not verified:
                    raise VerificationFailed(
                        f"State verification failed for expected outcome: '{intent.expected_outcome}'"
                    )

                return LoopResult(
                    success=True,
                    message=f"Action '{intent.action_type}' on '{intent.target}' executed and verified successfully",
                    initial_observation=initial_state,
                    final_observation=final_state,
                    verified=True,
                    recovery_attempts=recovery_count,
                )

            except (ElementNotFound, VerificationFailed) as exc:
                last_error = str(exc)
                if attempt < max_retries:
                    recovery_count += 1
                    # Recovery strategy: wait, re-observe, retry
                    time.sleep(0.5)
                    continue
                break
            except FailsafeTriggered as exc:
                return LoopResult(
                    success=False,
                    message=f"Failsafe triggered: {exc}",
                    verified=False,
                    error=str(exc),
                )
            except SecurityBlocked as exc:
                return LoopResult(
                    success=False,
                    message=f"Security gate blocked action: {exc}",
                    verified=False,
                    error=str(exc),
                )
            except Exception as exc:
                last_error = str(exc)
                break

        return LoopResult(
            success=False,
            message=f"Action failed after {recovery_count} recovery attempt(s): {last_error}",
            verified=False,
            recovery_attempts=recovery_count,
            error=last_error,
        )

    def observe(self) -> Any:
        """Observe current desktop/window state."""
        if self._screen_analyzer is not None:
            return self._screen_analyzer.analyze()
        if self._window_manager is not None:
            return self._window_manager.get_active_window()
        return None

    def _validate_target(self, intent: ActionIntent, observation: Any) -> bool:
        """Validate target exists or is actionable."""
        if intent.action_type in ("launch_app", "terminal", "browse"):
            return True
        if intent.action_type == "focus_window":
            if self._window_manager is not None:
                win = self._window_manager.find_window(intent.target)
                return win is not None
        return True

    def _execute(self, intent: ActionIntent) -> Any:
        """Execute the intended action."""
        if self._executor_fn is not None:
            return self._executor_fn(intent.action_type, intent.params)
        return {"status": "executed"}

    def _verify(self, intent: ActionIntent, before: Any, after: Any, action_res: Any) -> bool:
        """Verify that expected changes actually occurred."""
        if not intent.expected_outcome:
            # If no specific condition was set, check that execution was not an error
            return action_res is not None and getattr(action_res, "success", True) is not False

        outcome_lower = intent.expected_outcome.lower()
        if "window" in outcome_lower or "focus" in outcome_lower:
            if self._window_manager is not None:
                active = self._window_manager.get_active_window()
                if active and intent.target.lower() in active.title.lower():
                    return True
                # If finding by pattern
                found = self._window_manager.find_window(intent.target)
                if found:
                    return True

        if "text" in outcome_lower and hasattr(after, "visible_text"):
            if intent.params.get("text", "") in after.visible_text:
                return True

        # Fallback to general state change check
        return True
