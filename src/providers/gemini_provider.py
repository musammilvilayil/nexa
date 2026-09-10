from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from core.contracts import RiskTier
from providers.contracts import (
    VisionProvider,
    VisionResult,
    BoundingBox,
    UIElement,
)


@dataclass(frozen=True)
class ActionProposal:
    """A proposal from Gemini Computer Use to be validated by NEXA."""
    action_type: str
    target: str
    params: dict[str, Any] = field(default_factory=dict)
    risk_tier: RiskTier = RiskTier.MUTATE
    requires_confirmation: bool = True
    reasoning: str = ""
    is_injection_risk: bool = False
    injection_warnings: tuple[str, ...] = ()


class PromptInjectionDetector:
    """Heuristic scanner for adversarial prompt injections in multimodal / text inputs."""

    INJECTION_PATTERNS = (
        re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior)\s+(?:instructions|rules)\b", re.IGNORECASE),
        re.compile(r"\bsystem\s+(?:prompt|override|command)\b", re.IGNORECASE),
        re.compile(r"\byou\s+are\s+now\s+(?:an?\s+unrestricted|DAN|jailbreak)\b", re.IGNORECASE),
        re.compile(r"\bbypass\s+(?:security|failsafe|guardrails?|sandbox)\b", re.IGNORECASE),
        re.compile(r"\b(?:eval|exec|compile|__import__|subprocess)\s*\(", re.IGNORECASE),
        re.compile(r"\b(?:drop\s+database|drop\s+table|format\s+[c-z]:|rmdir\s+/s)\b", re.IGNORECASE),
        re.compile(r"\b(?:exfiltrate|curl\s+https?://|wget\s+https?://)\b", re.IGNORECASE),
        re.compile(r"data:text/html;base64,", re.IGNORECASE),
    )

    @classmethod
    def scan(cls, text: str) -> tuple[bool, list[str]]:
        """Scan text for injection attempts. Returns (is_suspicious, warnings)."""
        warnings = []
        for pat in cls.INJECTION_PATTERNS:
            match = pat.search(text)
            if match:
                warnings.append(f"Matched prompt injection indicator: '{match.group(0)}'")
        return bool(warnings), warnings


class GeminiVisionProvider:
    """Gemini-based vision and screen analysis provider.
    
    Adheres strictly to the VisionProvider protocol.
    Security Invariant:
    All actions suggested by vision analysis are advisory ONLY and must pass
    NEXA's local SecurityGate and FailsafeMonitor before execution.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._model = model or os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")

    def is_available(self) -> bool:
        return bool(self._api_key.strip())

    @property
    def model_name(self) -> str:
        return self._model

    def analyze(self, image: bytes, prompt: str) -> VisionResult:
        if not self.is_available():
            return VisionResult(description="Gemini Vision unavailable: GEMINI_API_KEY not configured")

        # Scan prompt for injection before calling model
        is_suspicious, warnings = PromptInjectionDetector.scan(prompt)
        if is_suspicious:
            return VisionResult(description=f"Blocked prompt injection in vision request: {warnings[0]}")

        try:
            from bridges import GeminiBridge
            bridge = GeminiBridge(api_key=self._api_key, model=self._model)
            full_prompt = (
                f"{prompt}\nAnalyze this screen image. Describe active windows and notable controls."
            )
            resp = bridge.generate_text(full_prompt)
            return VisionResult(
                description=resp,
                elements=(),
                raw={"response": resp},
            )
        except Exception as exc:
            return VisionResult(description=f"Gemini vision analysis error: {exc}")

    def locate_element(self, image: bytes, description: str) -> list[BoundingBox]:
        if not self.is_available():
            return []
        return []


class GeminiComputerUseProvider:
    """Provider wrapper for Gemini-driven computer actions.
    
    Authority Invariant:
    The local NEXA SecurityGate and FailsafeMonitor remain strictly authoritative.
    Model output is treated as untrusted proposals.
    """

    def __init__(
        self,
        vision_provider: GeminiVisionProvider | None = None,
        model: str | None = None,
    ) -> None:
        self._vision = vision_provider or GeminiVisionProvider()
        self._model = model or os.getenv("GEMINI_COMPUTER_USE_MODEL", "gemini-2.5-flash")

    def is_available(self) -> bool:
        return self._vision.is_available()

    @property
    def model_name(self) -> str:
        return self._model

    def propose_action(self, goal: str, screen_state: Any) -> ActionProposal:
        """Propose the next computer-use action for a given goal.
        
        Returns a structured ActionProposal. Does NOT execute it directly.
        """
        # 1. Scan user goal and screen text for prompt injection attempts
        screen_text = getattr(screen_state, "visible_text", "") or ""
        is_goal_suspicious, goal_warnings = PromptInjectionDetector.scan(goal)
        is_screen_suspicious, screen_warnings = PromptInjectionDetector.scan(screen_text)

        all_warnings = goal_warnings + screen_warnings
        if is_goal_suspicious or is_screen_suspicious:
            return ActionProposal(
                action_type="security_alert",
                target="prompt_injection_guard",
                params={"warnings": all_warnings},
                risk_tier=RiskTier.CRITICAL,
                requires_confirmation=True,
                reasoning=f"Potential prompt injection detected: {all_warnings[0] if all_warnings else 'unknown'}",
                is_injection_risk=True,
                injection_warnings=tuple(all_warnings),
            )

        # 2. If Gemini unavailable, use deterministic fallback proposal
        if not self.is_available():
            # Deterministic fallback mapping
            goal_lower = goal.lower()
            if "open" in goal_lower or "launch" in goal_lower:
                app = goal.split()[-1]
                return ActionProposal(
                    action_type="launch_app",
                    target=app,
                    params={"app_name": app},
                    risk_tier=RiskTier.MUTATE,
                    requires_confirmation=False,
                    reasoning=f"Deterministic fallback proposal: launch {app}",
                )
            if "close" in goal_lower:
                app = goal.split()[-1]
                return ActionProposal(
                    action_type="close_app",
                    target=app,
                    params={"app_name": app},
                    risk_tier=RiskTier.DESTRUCTIVE,
                    requires_confirmation=True,
                    reasoning=f"Deterministic fallback proposal: close {app}",
                )
            return ActionProposal(
                action_type="observe",
                target="current_desktop",
                risk_tier=RiskTier.READ,
                requires_confirmation=False,
                reasoning="Deterministic fallback proposal: observe current screen",
            )

        # 3. If Gemini is available, query model for structured proposal
        try:
            from bridges import GeminiBridge
            bridge = GeminiBridge(model=self._model)
            schema = {
                "type": "object",
                "properties": {
                    "action_type": {"type": "string"},
                    "target": {"type": "string"},
                    "params": {"type": "object"},
                    "risk_tier": {"type": "string", "enum": ["read", "mutate", "remote", "destructive", "critical"]},
                    "reasoning": {"type": "string"},
                },
                "required": ["action_type", "target"],
            }
            prompt = (
                f"Propose the next computer-use action for goal: '{goal}'. "
                f"Current active window: {getattr(screen_state, 'active_window', 'None')}. "
                f"Available tools: launch_app, close_app, click, type_text, hotkey, scroll, navigate_browser, observe."
            )
            raw = bridge.generate_json(prompt, schema)
            tier_map = {
                "read": RiskTier.READ,
                "mutate": RiskTier.MUTATE,
                "remote": RiskTier.REMOTE,
                "destructive": RiskTier.DESTRUCTIVE,
                "critical": RiskTier.CRITICAL,
            }
            risk = tier_map.get(raw.get("risk_tier", "mutate").lower(), RiskTier.MUTATE)
            req_confirm = risk in (RiskTier.REMOTE, RiskTier.DESTRUCTIVE, RiskTier.CRITICAL)
            return ActionProposal(
                action_type=raw.get("action_type", "observe"),
                target=raw.get("target", "screen"),
                params=raw.get("params", {}),
                risk_tier=risk,
                requires_confirmation=req_confirm,
                reasoning=raw.get("reasoning", "Gemini structured proposal"),
            )
        except Exception as exc:
            return ActionProposal(
                action_type="observe",
                target="current_desktop",
                risk_tier=RiskTier.READ,
                requires_confirmation=False,
                reasoning=f"Gemini error, fallback to observation: {exc}",
            )


# Canonical alias for provider architecture
GeminiProvider = GeminiComputerUseProvider
