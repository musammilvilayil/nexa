from __future__ import annotations
import os
from voice.contracts import AudioSegment, TranscriptionResult

class VoskSTT:
    """Offline STT using Vosk."""
    def __init__(self, model_path: str | None = None, language: str = "en") -> None:
        self._model_path = model_path
        self._language = language

    def transcribe(self, audio: AudioSegment, *, language: str = "auto") -> TranscriptionResult:
        if not self.is_available():
            raise RuntimeError("Vosk is not available")
        return TranscriptionResult(text="")

    def is_available(self) -> bool:
        try:
            import vosk  # type: ignore
            return True
        except ImportError:
            return False

    @property
    def name(self) -> str:
        return "vosk"

class GeminiSTT:
    """Online STT using Gemini multimodal API."""
    def __init__(self) -> None:
        pass

    def transcribe(self, audio: AudioSegment, *, language: str = "auto") -> TranscriptionResult:
        if not self.is_available():
            raise RuntimeError("Gemini STT is not available")
        return TranscriptionResult(text="")

    def is_available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    @property
    def name(self) -> str:
        return "gemini"
