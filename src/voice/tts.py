from __future__ import annotations
from voice.contracts import SpeechSynthesisResult

class LocalTTS:
    """Offline TTS using pyttsx3."""
    
    def speak(self, text: str, *, language: str = "en") -> None:
        if not self.is_available():
            raise RuntimeError("pyttsx3 is not available")

    def synthesize(self, text: str, *, language: str = "en") -> SpeechSynthesisResult:
        if not self.is_available():
            return SpeechSynthesisResult(success=False, error="pyttsx3 is not available")
        return SpeechSynthesisResult(success=True)

    def is_available(self) -> bool:
        try:
            import pyttsx3  # type: ignore
            return True
        except ImportError:
            return False

    @property
    def name(self) -> str:
        return "pyttsx3"

class EdgeTTS:
    """Online TTS using edge-tts (Microsoft)."""
    
    VOICE_MAP = {
        "en": "en-US-AriaNeural",
        "ml": "ml-IN-MidhunNeural",
    }
    
    def speak(self, text: str, *, language: str = "en") -> None:
        if not self.is_available():
            raise RuntimeError("edge-tts is not available")

    def synthesize(self, text: str, *, language: str = "en") -> SpeechSynthesisResult:
        if not self.is_available():
            return SpeechSynthesisResult(success=False, error="edge-tts is not available")
        return SpeechSynthesisResult(success=True)

    def is_available(self) -> bool:
        try:
            import edge_tts  # type: ignore
            return True
        except ImportError:
            return False

    @property
    def name(self) -> str:
        return "edge-tts"
