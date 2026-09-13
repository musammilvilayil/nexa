from __future__ import annotations

import sys
from typing import Any

from voice.listener import VoiceListener
from voice.stt import VoskSTT, GeminiSTT
from voice.tts import LocalTTS, EdgeTTS
from voice.wake_word import SimpleWakeWord


def get_voice_status() -> dict[str, Any]:
    """Retrieve comprehensive diagnostic status of the NEXA voice subsystem."""
    listener = VoiceListener()
    mic_available = listener.is_available()
    mic_name = listener.get_input_device_name() if mic_available else "None"

    vosk = VoskSTT()
    vosk_lib_installed = vosk.is_available()
    vosk_model_found = vosk.has_model()

    gemini_stt = GeminiSTT()
    gemini_stt_available = gemini_stt.is_available()

    local_tts = LocalTTS()
    local_tts_available = local_tts.is_available()

    edge_tts = EdgeTTS()
    edge_tts_available = edge_tts.is_available()

    wake_word = SimpleWakeWord(wake_word="nexa")

    missing = []
    if not mic_available:
        missing.append("microphone")
    if not vosk_model_found:
        missing.append(f"vosk model at {vosk.model_path}")
    if not gemini_stt_available:
        missing.append("GEMINI_API_KEY for online STT")

    overall_tts = "pyttsx3 (local)" if local_tts_available else ("edge-tts (online)" if edge_tts_available else "none")
    overall_stt = "vosk (offline)" if (vosk_lib_installed and vosk_model_found) else ("gemini (online)" if gemini_stt_available else "unconfigured")

    return {
        "microphone_available": mic_available,
        "microphone_device": mic_name,
        "stt_provider": overall_stt,
        "vosk_installed": vosk_lib_installed,
        "vosk_model_path": vosk.model_path,
        "vosk_model_found": vosk_model_found,
        "gemini_stt_available": gemini_stt_available,
        "tts_provider": overall_tts,
        "pyttsx3_available": local_tts_available,
        "edge_tts_available": edge_tts_available,
        "wake_word": wake_word.wake_word,
        "language_support": ["en (English)", "ml (Malayalam)", "manglish (Malayalam in Latin script)"],
        "overall_voice_ready": mic_available and (local_tts_available or edge_tts_available),
        "missing_dependencies": missing,
    }


def format_voice_status(status: dict[str, Any]) -> str:
    """Format voice status dictionary into a user-friendly CLI string."""
    lines = [
        "NEXA Voice Subsystem Diagnostics (/voice-status):",
        f"  Microphone: {'CONNECTED' if status['microphone_available'] else 'NOT DETECTED'} ({status['microphone_device']})",
        f"  STT Engine: {status['stt_provider']}",
        f"    - Vosk library: {'INSTALLED' if status['vosk_installed'] else 'NOT INSTALLED'}",
        f"    - Vosk model: {'FOUND' if status['vosk_model_found'] else 'MISSING (place at ' + str(status['vosk_model_path']) + ')'}",
        f"    - Gemini STT: {'AVAILABLE' if status['gemini_stt_available'] else 'KEY NOT SET'}",
        f"  TTS Engine: {status['tts_provider']}",
        f"    - pyttsx3 (offline): {'AVAILABLE' if status['pyttsx3_available'] else 'NOT INSTALLED'}",
        f"    - edge-tts (neural online): {'AVAILABLE' if status['edge_tts_available'] else 'NOT INSTALLED'}",
        f"  Wake Word: \"{status['wake_word']}\"",
        f"  Language support: {', '.join(status['language_support'])}",
        f"  Voice readiness: {'READY FOR AUDIO INTERACTION' if status['overall_voice_ready'] else 'PARTIALLY CONFIGURED'}",
    ]
    if status["missing_dependencies"]:
        lines.append(f"  Notes: {', '.join(status['missing_dependencies'])}")
    return "\n".join(lines)
