from __future__ import annotations

import re
import time
from typing import Sequence

from .contracts import PolicyDecision, PolicyOutcome, RiskTier


# Operations that must NEVER execute, regardless of confirmation.
# Patterns are case-insensitive regexes matched against the raw user text.
DEFAULT_DENY_PATTERNS: tuple[str, ...] = (
    r"\bformat\s+[a-z]:",                     # format C:
    r"\brm\s+(-\w+\s+)*-rf\s+/",             # rm -rf / (with optional extra flags)
    r"\bdel\s+(/[a-z]\s+)*[a-z]:\\",          # del /s /q C:\... or del /q /s
    r"\brmdir\s+(/[a-z]\s+)*[a-z]:\\",        # rmdir /s /q C:\...
    r"\brd\s+(/[a-z]\s+)*[a-z]:\\",           # rd /s /q C:\...
    r"\bremove-item\s+.*[a-z]:\\windows\b",   # PowerShell Remove-Item
    r"\bdelete\s+(?:the\s+)?windows\s+(?:system\s+)?directory\b", # natural language
    r"\bdelete\s+(?:the\s+)?system\s+directory\b",
    r"\bmkfs\b",                               # mkfs (Linux format)
    r"\bshutdown\s+[/-][srf]",                # shutdown /s, -s, /r, -r, /f, -f
    r"\breg\s+delete\s+hk",                   # registry deletion
    r"\bbcdedit\b",                            # boot config editing
    r"\bdiskpart\b",                           # disk partition tool
    r":\(\)\s*\{",                             # bash fork bomb
)


class SecurityGate:
    """Kernel-level risk policy independent of any specific capability.

    Handles five risk tiers:

    - READ / MUTATE → ALLOW (no confirmation needed)
    - REMOTE / DESTRUCTIVE → REQUIRE_CONFIRMATION (user must confirm)
    - CRITICAL → REQUIRE_CONFIRMATION + mandatory cooldown before execution

    A configurable deny-list can unconditionally block operations by matching
    user text against forbidden patterns, returning DENY with no confirmation
    path.

    The cooldown for CRITICAL operations ensures a minimum delay (default 5s)
    between confirmation and execution, preventing accidental rapid-fire
    confirmation of high-danger actions.
    """

    def __init__(
        self,
        *,
        deny_patterns: Sequence[str] | None = None,
        critical_cooldown_seconds: float = 5.0,
    ) -> None:
        raw = deny_patterns if deny_patterns is not None else DEFAULT_DENY_PATTERNS
        self._deny_patterns = tuple(
            re.compile(pattern, re.IGNORECASE) for pattern in raw
        )
        self._critical_cooldown_seconds = max(0.0, float(critical_cooldown_seconds))
        # Tracks when CRITICAL actions were confirmed for cooldown enforcement
        self._critical_confirmations: dict[str, float] = {}

    @property
    def critical_cooldown_seconds(self) -> float:
        return self._critical_cooldown_seconds

    def evaluate(
        self,
        skill_name: str = "",
        operation: str = "",
        params: dict | None = None,
        risk: RiskTier = RiskTier.MUTATE,
        confirmed: bool = False,
    ) -> PolicyDecision:
        """Convenience evaluation method for action proposals."""
        return self.decide(risk, confirmed=confirmed)

    def decide(self, risk: RiskTier, *, confirmed: bool = False) -> PolicyDecision:
        """Evaluate a risk tier and return a policy decision.

        Backward-compatible: READ/MUTATE → ALLOW, REMOTE/DESTRUCTIVE →
        REQUIRE_CONFIRMATION (or ALLOW if confirmed).

        New: CRITICAL → REQUIRE_CONFIRMATION (or ALLOW if confirmed).
        The caller is responsible for enforcing cooldown timing for CRITICAL.
        """
        if risk in {RiskTier.READ, RiskTier.MUTATE}:
            return PolicyDecision(PolicyOutcome.ALLOW)

        if risk in {RiskTier.REMOTE, RiskTier.DESTRUCTIVE}:
            if confirmed:
                return PolicyDecision(PolicyOutcome.ALLOW, "User confirmed pending action")
            return PolicyDecision(
                PolicyOutcome.REQUIRE_CONFIRMATION,
                f"{risk.value} operation requires explicit confirmation",
            )

        if risk == RiskTier.CRITICAL:
            if confirmed:
                return PolicyDecision(
                    PolicyOutcome.ALLOW,
                    "User confirmed critical action",
                )
            return PolicyDecision(
                PolicyOutcome.REQUIRE_CONFIRMATION,
                f"CRITICAL operation requires explicit confirmation (cooldown: {self._critical_cooldown_seconds}s)",
            )

        return PolicyDecision(PolicyOutcome.DENY, "Unknown risk tier")

    def check_deny_list(self, text: str) -> PolicyDecision | None:
        """Check user text against the deny list.

        Returns a DENY PolicyDecision if the text matches any denied pattern,
        or None if the text is not denied.
        """
        for pattern in self._deny_patterns:
            if pattern.search(text):
                return PolicyDecision(
                    PolicyOutcome.DENY,
                    f"Operation blocked by security deny list (matched: {pattern.pattern})",
                )
        return None

    def record_critical_confirmation(self, action_id: str) -> None:
        """Record the timestamp when a CRITICAL action was confirmed.

        Used for cooldown enforcement.
        """
        self._critical_confirmations[action_id] = time.monotonic()

    def check_critical_cooldown(self, action_id: str) -> float:
        """Check remaining cooldown for a CRITICAL confirmation.

        Returns 0.0 if cooldown has elapsed, or the remaining seconds.
        """
        confirmed_at = self._critical_confirmations.get(action_id)
        if confirmed_at is None:
            return 0.0
        elapsed = time.monotonic() - confirmed_at
        remaining = self._critical_cooldown_seconds - elapsed
        return max(0.0, remaining)

    def clear_critical_confirmation(self, action_id: str) -> None:
        """Clear the cooldown record for a completed CRITICAL action."""
        self._critical_confirmations.pop(action_id, None)
