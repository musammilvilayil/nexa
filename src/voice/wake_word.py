from __future__ import annotations
from voice.contracts import AudioSegment, STTProvider

class SimpleWakeWord:
    """Simple string-matching wake word detector.
    
    Works with any STT provider - checks if transcribed text starts with the wake word.
    """
    def __init__(self, wake_word: str = "nexa", stt: STTProvider | None = None) -> None:
        self._wake_word = wake_word.lower()
        self._stt = stt

    def detect(self, audio: AudioSegment) -> bool:
        if not self._stt:
            return False
        
        result = self._stt.transcribe(audio)
        if not result:
            return False
            
        return result.text.lower().startswith(self._wake_word)

    def is_available(self) -> bool:
        return self._stt is not None and self._stt.is_available()

    @property
    def wake_word(self) -> str:
        return self._wake_word
