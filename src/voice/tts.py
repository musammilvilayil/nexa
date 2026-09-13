from __future__ import annotations

import asyncio
import io
import os
import tempfile
from voice.contracts import SpeechSynthesisResult


class LocalTTS:
    """Offline TTS using pyttsx3."""

    def __init__(self) -> None:
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            import pyttsx3
            self._engine = pyttsx3.init()
        return self._engine

    def speak(self, text: str, *, language: str = "en") -> None:
        if not self.is_available():
            raise RuntimeError("pyttsx3 is not available")
        try:
            engine = self._get_engine()
            engine.say(text)
            engine.runAndWait()
        except Exception as exc:
            raise RuntimeError(f"Local TTS playback failed: {exc}") from exc

    def synthesize(self, text: str, *, language: str = "en") -> SpeechSynthesisResult:
        if not self.is_available():
            return SpeechSynthesisResult(success=False, error="pyttsx3 is not available")
        try:
            engine = self._get_engine()
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            try:
                engine.save_to_file(text, tmp_path)
                engine.runAndWait()
                with open(tmp_path, "rb") as f:
                    audio_bytes = f.read()
                return SpeechSynthesisResult(
                    audio_data=audio_bytes,
                    format="wav",
                    success=True,
                )
            finally:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
        except Exception as exc:
            return SpeechSynthesisResult(success=False, error=str(exc))

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
    """Online high-quality neural TTS using edge-tts (Microsoft)."""

    VOICE_MAP = {
        "en": "en-US-AriaNeural",
        "ml": "ml-IN-MidhunNeural",  # Malayalam
    }

    def speak(self, text: str, *, language: str = "en") -> None:
        res = self.synthesize(text, language=language)
        if not res.success:
            raise RuntimeError(f"EdgeTTS speak failed: {res.error}")

    def synthesize(self, text: str, *, language: str = "en") -> SpeechSynthesisResult:
        if not self.is_available():
            return SpeechSynthesisResult(success=False, error="edge-tts is not available")

        voice = self.VOICE_MAP.get(language, "en-US-AriaNeural")

        async def _run():
            import edge_tts
            communicate = edge_tts.Communicate(text, voice)
            stream = io.BytesIO()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    stream.write(chunk["data"])
            return stream.getvalue()

        try:
            audio_data = asyncio.run(_run())
            return SpeechSynthesisResult(
                audio_data=audio_data,
                format="mp3",
                success=True,
            )
        except Exception as exc:
            return SpeechSynthesisResult(success=False, error=str(exc))

    def is_available(self) -> bool:
        try:
            import edge_tts  # type: ignore
            return True
        except ImportError:
            return False

    @property
    def name(self) -> str:
        return "edge-tts"
