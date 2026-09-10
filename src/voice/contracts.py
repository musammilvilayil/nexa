from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Protocol

class VoiceMode(str, Enum):
    PUSH_TO_TALK = "push_to_talk"
    CONTINUOUS = "continuous"
    WAKE_WORD = "wake_word"

@dataclass(frozen=True)
class AudioSegment:
    data: bytes
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2  # 16-bit
    duration_seconds: float = 0.0

@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    confidence: float = 1.0
    language: str = "en"
    is_final: bool = True
    alternatives: tuple[str, ...] = ()
    raw: Any = None

@dataclass(frozen=True)
class SpeechSynthesisResult:
    audio_data: bytes = b""
    format: str = "wav"
    success: bool = True
    error: str | None = None

class STTProvider(Protocol):
    def transcribe(self, audio: AudioSegment, *, language: str = "auto") -> TranscriptionResult: ...
    def is_available(self) -> bool: ...
    @property
    def name(self) -> str: ...

class TTSProvider(Protocol):
    def speak(self, text: str, *, language: str = "en") -> None: ...
    def synthesize(self, text: str, *, language: str = "en") -> SpeechSynthesisResult: ...
    def is_available(self) -> bool: ...
    @property
    def name(self) -> str: ...

class WakeWordProvider(Protocol):
    def detect(self, audio: AudioSegment) -> bool: ...
    def is_available(self) -> bool: ...
    @property
    def wake_word(self) -> str: ...
