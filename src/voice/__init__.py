from __future__ import annotations

from voice.contracts import (
    VoiceMode,
    AudioSegment,
    TranscriptionResult,
    SpeechSynthesisResult,
    STTProvider,
    TTSProvider,
    WakeWordProvider,
)
from voice.listener import VoiceListener
from voice.stt import VoskSTT, GeminiSTT
from voice.tts import LocalTTS, EdgeTTS
from voice.wake_word import SimpleWakeWord
from voice.voice_loop import VoiceLoop

__all__ = [
    "VoiceMode",
    "AudioSegment",
    "TranscriptionResult",
    "SpeechSynthesisResult",
    "STTProvider",
    "TTSProvider",
    "WakeWordProvider",
    "VoiceListener",
    "VoskSTT",
    "GeminiSTT",
    "LocalTTS",
    "EdgeTTS",
    "SimpleWakeWord",
    "VoiceLoop",
]
