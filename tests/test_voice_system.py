import sys
import os
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from voice.contracts import VoiceMode, AudioSegment, TranscriptionResult, SpeechSynthesisResult
from voice.stt import VoskSTT, GeminiSTT
from voice.tts import LocalTTS, EdgeTTS
from voice.wake_word import SimpleWakeWord
from voice.listener import VoiceListener
from voice.voice_loop import VoiceLoop

class MockSTT:
    def __init__(self, return_text="hello"):
        self.return_text = return_text
    
    def transcribe(self, audio, *, language="auto"):
        return TranscriptionResult(text=self.return_text)
        
    def is_available(self):
        return True
        
    @property
    def name(self):
        return "mock"

class TestVoiceSystem(unittest.TestCase):
    def test_audio_segment_creation(self):
        audio = AudioSegment(data=b"test", sample_rate=16000)
        self.assertEqual(audio.data, b"test")
        self.assertEqual(audio.sample_rate, 16000)
        
    def test_transcription_result(self):
        result = TranscriptionResult(text="hello", confidence=0.9)
        self.assertEqual(result.text, "hello")
        self.assertEqual(result.confidence, 0.9)
        
    def test_speech_synthesis_result(self):
        result = SpeechSynthesisResult(success=True, audio_data=b"test")
        self.assertTrue(result.success)
        self.assertEqual(result.audio_data, b"test")

    def test_voice_mode_enum(self):
        self.assertEqual(VoiceMode.PUSH_TO_TALK.value, "push_to_talk")
        self.assertEqual(VoiceMode.CONTINUOUS.value, "continuous")
        self.assertEqual(VoiceMode.WAKE_WORD.value, "wake_word")

    def test_vosk_stt_unavailable(self):
        stt = VoskSTT()
        # Ensure vosk is not installed or mocked correctly
        try:
            import vosk
            pass # if vosk exists, this test behavior depends on env
        except ImportError:
            self.assertFalse(stt.is_available())

    def test_gemini_stt_unavailable_without_key(self):
        stt = GeminiSTT()
        original = os.environ.get("GEMINI_API_KEY")
        if "GEMINI_API_KEY" in os.environ:
            del os.environ["GEMINI_API_KEY"]
        self.assertFalse(stt.is_available())
        if original is not None:
            os.environ["GEMINI_API_KEY"] = original

    def test_local_tts_unavailable(self):
        tts = LocalTTS()
        try:
            import pyttsx3
        except ImportError:
            self.assertFalse(tts.is_available())

    def test_edge_tts_unavailable(self):
        tts = EdgeTTS()
        try:
            import edge_tts
        except ImportError:
            self.assertFalse(tts.is_available())

    def test_simple_wake_word_creation(self):
        ww = SimpleWakeWord()
        self.assertEqual(ww.wake_word, "nexa")
        
    def test_voice_listener_creation(self):
        listener = VoiceListener()
        self.assertFalse(listener.is_listening)
        
    def test_voice_loop_creation(self):
        loop = VoiceLoop()
        self.assertFalse(loop.is_running)
        self.assertEqual(loop.mode, VoiceMode.PUSH_TO_TALK)
        
    def test_voice_loop_process_audio_with_mock_stt(self):
        stt = MockSTT(return_text="hello world")
        
        callback_called = False
        def mock_callback(text: str) -> str:
            nonlocal callback_called
            callback_called = True
            self.assertEqual(text, "hello world")
            return "response"
            
        loop = VoiceLoop(stt=stt, kernel_callback=mock_callback, mode=VoiceMode.CONTINUOUS)
        loop.start()
        
        audio = AudioSegment(data=b"")
        response = loop.process_audio(audio)
        
        self.assertTrue(callback_called)
        self.assertEqual(response, "response")

if __name__ == "__main__":
    unittest.main()
