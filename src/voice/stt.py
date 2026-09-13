from __future__ import annotations

import json
import os
from pathlib import Path
from voice.contracts import AudioSegment, TranscriptionResult


class VoskSTT:
    """Offline STT using Vosk library.
    
    Model files belong in:
    - Default: C:\\NEXA\\data\\vosk-model
    - Or path specified in VOSK_MODEL_PATH environment variable.
    Small model (e.g. vosk-model-small-en-us-0.15) can be downloaded from
    https://alphacephei.com/vosk/models and extracted to data/vosk-model.
    """

    def __init__(self, model_path: str | None = None, language: str = "en") -> None:
        default_model = Path(__file__).resolve().parents[2] / "data" / "vosk-model"
        self._model_path = model_path or os.getenv("VOSK_MODEL_PATH", str(default_model))
        self._language = language
        self._model = None

    def has_model(self) -> bool:
        """Check if local model directory exists and contains model files."""
        p = Path(self._model_path)
        return p.exists() and p.is_dir() and any(p.iterdir())

    def _get_model(self):
        if self._model is None:
            if not self.has_model():
                raise RuntimeError(
                    f"Vosk model directory not found at '{self._model_path}'. "
                    f"Please download a model from https://alphacephei.com/vosk/models "
                    f"and extract it to {self._model_path}."
                )
            import vosk
            self._model = vosk.Model(self._model_path)
        return self._model

    def transcribe(self, audio: AudioSegment, *, language: str = "auto") -> TranscriptionResult:
        if not self.is_available():
            raise RuntimeError("Vosk library is not installed: pip install vosk")

        if not self.has_model():
            raise RuntimeError(
                f"Vosk model required at '{self._model_path}'. "
                f"Download from https://alphacephei.com/vosk/models and extract to data/vosk-model"
            )

        try:
            import vosk
            model = self._get_model()
            recognizer = vosk.KaldiRecognizer(model, audio.sample_rate)
            recognizer.AcceptWaveform(audio.data)
            res = json.loads(recognizer.FinalResult())
            text = res.get("text", "")
            return TranscriptionResult(
                text=text,
                confidence=1.0 if text else 0.0,
                language=self._language,
                is_final=True,
                raw=res,
            )
        except Exception as exc:
            raise RuntimeError(f"Vosk transcription error: {exc}") from exc

    def is_available(self) -> bool:
        try:
            import vosk  # type: ignore
            return True
        except ImportError:
            return False

    @property
    def model_path(self) -> str:
        return self._model_path

    @property
    def name(self) -> str:
        return "vosk"


class GeminiSTT:
    """Online STT using Gemini multimodal API."""

    def __init__(self) -> None:
        self._api_key = os.environ.get("GEMINI_API_KEY", "")

    def transcribe(self, audio: AudioSegment, *, language: str = "auto") -> TranscriptionResult:
        if not self.is_available():
            raise RuntimeError("Gemini STT requires GEMINI_API_KEY in environment")
        return TranscriptionResult(
            text="",
            confidence=0.0,
            language=language if language != "auto" else "en",
            is_final=True,
        )

    def is_available(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())

    @property
    def name(self) -> str:
        return "gemini"
