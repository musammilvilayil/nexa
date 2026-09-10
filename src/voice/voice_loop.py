from __future__ import annotations
from typing import Callable
from voice.contracts import VoiceMode, AudioSegment, STTProvider, TTSProvider, WakeWordProvider
from voice.listener import VoiceListener

class VoiceLoop:
    """Main voice interaction loop.
    
    Integrates: Listener + STT + Kernel + TTS
    
    Modes:
    - WAKE_WORD: Listen for wake word, then transcribe and process
    - CONTINUOUS: Always transcribe and process
    - PUSH_TO_TALK: Wait for explicit trigger, then record and process
    """
    def __init__(
        self,
        listener: VoiceListener | None = None,
        stt: STTProvider | None = None,
        tts: TTSProvider | None = None,
        wake_word: WakeWordProvider | None = None,
        kernel_callback: Callable[[str], str] | None = None,
        mode: VoiceMode = VoiceMode.PUSH_TO_TALK,
    ) -> None:
        self._listener = listener
        self._stt = stt
        self._tts = tts
        self._wake_word = wake_word
        self._kernel_callback = kernel_callback
        self._mode = mode
        self._is_running = False

    def start(self) -> None:
        self._is_running = True
        if self._listener:
            self._listener.start_listening()

    def stop(self) -> None:
        self._is_running = False
        if self._listener:
            self._listener.stop_listening()

    def process_audio(self, audio: AudioSegment) -> str | None:
        if not self._is_running or not self._stt:
            return None
            
        if self._mode == VoiceMode.WAKE_WORD:
            if self._wake_word and not self._wake_word.detect(audio):
                return None
                
        transcription = self._stt.transcribe(audio)
        text = transcription.text.strip()
        
        if not text:
            return None
            
        if self._kernel_callback:
            response = self._kernel_callback(text)
            if self._tts and response:
                self._tts.speak(response)
            return response
            
        return None

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def mode(self) -> VoiceMode:
        return self._mode
