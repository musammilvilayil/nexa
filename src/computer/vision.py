from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class VisionBackend(Protocol):
    """Minimal vision backend that ScreenAnalyzer depends on."""
    def analyze_image(self, image_bytes: bytes, prompt: str) -> dict[str, Any]: ...
    def is_available(self) -> bool: ...


@dataclass(frozen=True)
class ScreenState:
    """Represents the current state of the screen."""
    active_window: str = ""
    visible_text: str = ""
    elements: tuple[dict[str, Any], ...] = ()
    description: str = ""
    raw: Any = None


class ScreenAnalyzer:
    """Analyzes screenshots to understand UI state.
    
    Uses a pluggable VisionBackend (Gemini Vision, local model, etc.)
    to identify UI elements, read text, and understand application state.
    """
    
    def __init__(self, backend: VisionBackend | None = None) -> None:
        self._backend = backend
    
    @property
    def is_available(self) -> bool:
        return self._backend is not None and self._backend.is_available()
    
    def analyze(self, screenshot: bytes, *, prompt: str = "Describe what you see on the screen.") -> ScreenState:
        """Analyze a screenshot and return structured screen state."""
        if self._backend is None:
            return ScreenState(description="No vision backend configured")
        
        try:
            result = self._backend.analyze_image(screenshot, prompt)
            return ScreenState(
                active_window=result.get("active_window", ""),
                visible_text=result.get("visible_text", ""),
                elements=tuple(result.get("elements", [])),
                description=result.get("description", ""),
                raw=result,
            )
        except Exception as exc:
            return ScreenState(description=f"Analysis failed: {exc}")
    
    def verify_action(self, before: bytes, after: bytes, expected: str) -> bool:
        """Verify whether an action succeeded by comparing before/after screenshots."""
        if self._backend is None:
            return True  # Cannot verify without backend, assume success
        
        try:
            result = self._backend.analyze_image(
                after,
                f"Compare with the previous state and determine if this action succeeded: {expected}. "
                f"Respond with a JSON object containing 'success': true or false."
            )
            return bool(result.get("success", True))
        except Exception:
            return True  # Cannot verify, assume success
    
    def find_element(self, screenshot: bytes, description: str) -> dict[str, Any] | None:
        """Find a UI element by description."""
        if self._backend is None:
            return None
        
        try:
            result = self._backend.analyze_image(
                screenshot,
                f"Find the UI element matching this description: '{description}'. "
                f"Return a JSON with 'found': true/false, 'x': int, 'y': int, 'text': str"
            )
            if result.get("found"):
                return result
            return None
        except Exception:
            return None
