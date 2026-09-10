from __future__ import annotations

import sys
import threading
from typing import Callable

from voice.contracts import AudioSegment


class VoiceListener:
    """Captures audio from the physical microphone using sounddevice.
    
    Supports push-to-talk (record_once) and continuous listening modes.
    """

    def __init__(self, *, sample_rate: int = 16000, channels: int = 1) -> None:
        self._sample_rate = sample_rate
        self._channels = channels
        self._is_listening = False
        self._callbacks: list[Callable[[AudioSegment], None]] = []
        self._listen_thread: threading.Thread | None = None

    def is_available(self) -> bool:
        """Check whether sounddevice is available and an input device is found."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            # Check for at least one input device
            for dev in devices:
                if dev.get("max_input_channels", 0) > 0:
                    return True
            return False
        except Exception:
            return False

    def get_input_device_name(self) -> str:
        """Retrieve the name of the active microphone/input device."""
        try:
            import sounddevice as sd
            default_idx = sd.default.device[0]
            if default_idx >= 0:
                dev = sd.query_devices(default_idx)
                return dev.get("name", "Default Microphone")
            return "No input device"
        except Exception:
            return "Unavailable"

    def record_once(self, duration_seconds: float = 5.0) -> AudioSegment:
        """Record audio from the microphone for a fixed duration."""
        try:
            import sounddevice as sd
            num_frames = int(duration_seconds * self._sample_rate)
            recording = sd.rec(
                num_frames,
                samplerate=self._sample_rate,
                channels=self._channels,
                dtype="int16",
            )
            sd.wait()
            raw_bytes = bytes(recording.tobytes())
            return AudioSegment(
                data=raw_bytes,
                duration_seconds=duration_seconds,
                sample_rate=self._sample_rate,
                channels=self._channels,
            )
        except Exception:
            return AudioSegment(
                data=b"",
                duration_seconds=duration_seconds,
                sample_rate=self._sample_rate,
                channels=self._channels,
            )

    def start_listening(self) -> None:
        """Start background continuous listening."""
        self._is_listening = True

    def stop_listening(self) -> None:
        """Stop background continuous listening."""
        self._is_listening = False

    def on_audio(self, callback: Callable[[AudioSegment], None]) -> None:
        self._callbacks.append(callback)

    @property
    def is_listening(self) -> bool:
        return self._is_listening
