from __future__ import annotations

import os
from typing import Any

from providers.contracts import (
    VisionProvider,
    VisionResult,
    BoundingBox,
    UIElement,
)


class GeminiVisionProvider:
    """Gemini-based vision and screen analysis provider.
    
    Adheres strictly to the VisionProvider protocol.
    Security Invariant:
    All actions suggested by vision analysis are advisory ONLY and must pass
    NEXA's local SecurityGate and FailsafeMonitor before execution.
    """

    def __init__(self, api_key: str | None = None, model: str = "gemini-2.5-flash") -> None:
        self._api_key = api_key or os.getenv("GEMINI_API_KEY", "")
        self._model = model

    def is_available(self) -> bool:
        return bool(self._api_key.strip())

    def analyze(self, image: bytes, prompt: str) -> VisionResult:
        if not self.is_available():
            return VisionResult(description="Gemini Vision unavailable: GEMINI_API_KEY not configured")

        try:
            from bridges import GeminiBridge
            bridge = GeminiBridge(api_key=self._api_key, model=self._model)
            # Structured prompt
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
        # Fallback to empty list; never fabricate coordinates
        return []


class GeminiComputerUseProvider:
    """Provider wrapper for Gemini-driven computer actions.
    
    Authority Invariant:
    The local NEXA SecurityGate and FailsafeMonitor remain strictly authoritative.
    Model output is treated as untrusted proposals.
    """

    def __init__(self, vision_provider: GeminiVisionProvider | None = None) -> None:
        self._vision = vision_provider or GeminiVisionProvider()

    def is_available(self) -> bool:
        return self._vision.is_available()

    def propose_action(self, goal: str, screen_state: Any) -> dict[str, Any]:
        """Propose the next computer-use action for a given goal.
        
        Returns a structured proposal. Does NOT execute it directly.
        """
        if not self.is_available():
            return {
                "action": "none",
                "reason": "Gemini provider unavailable",
                "requires_confirmation": False,
            }

        return {
            "action": "propose",
            "goal": goal,
            "requires_confirmation": True,
        }
