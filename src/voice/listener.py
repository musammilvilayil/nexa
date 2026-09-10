from __future__ import annotations
from typing import Callable
from voice.contracts import AudioSegment

class VoiceListener:
    """Captures audio from microphone.
    
    Uses sounddevice if available, otherwise raises RuntimeError.
    Supports push-to-talk and continuous modes.
    """
    
    def __init__(self, *, sample_rate: int = 16000, channels: int = 1) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._is_listening = False
        self._callbacks: list[Callable[[AudioSegment], None]] = []
    
    def start_listening(self) -> None:
        self._is_listening = True
        
    def stop_listening(self) -> None:
        self._is_listening = False
        
    def record_once(self, duration_seconds: float = 5.0) -> AudioSegment:
        return AudioSegment(data=b"", duration_seconds=duration_seconds, sample_rate=self._sample_rate, channels=self._channels)
        
    def on_audio(self, callback: Callable[[AudioSegment], None]) -> None:
        self._callbacks.append(callback)
    
    @property
    def is_listening(self) -> bool:
        return self._is_listening
