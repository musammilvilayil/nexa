"""Capability-agnostic resource bridges used by NEXA skills."""

from .gemini_bridge import GeminiBridge, GeminiBridgeError
from .ollama_bridge import OllamaBridge, OllamaBridgeError
from .subprocess_bridge import ProcessResult, SubprocessBridge, SubprocessBridgeError

__all__ = [
    "GeminiBridge",
    "GeminiBridgeError",
    "OllamaBridge",
    "OllamaBridgeError",
    "ProcessResult",
    "SubprocessBridge",
    "SubprocessBridgeError",
]
