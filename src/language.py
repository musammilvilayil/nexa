import json
import re
from dataclasses import dataclass

import httpx

from memory import (
    get_language_cache,
    get_teacher_example,
    save_language_cache,
    save_teacher_example,
)
from teacher import normalize_manglish, teacher_available

MALAYALAM_RE = re.compile(r"[\u0D00-\u0D7F]")
WORD_RE = re.compile(r"[A-Za-z']+")

MANGGLISH_HINTS = {
    "aanu",
    "aano",
    "ahno",
    "alle",
    "alla",
    "entha",
    "enthu",
    "ente",
    "njan",
    "njn",
    "namukku",
    "nammal",
    "ippo",
    "ivide",
    "avide",
    "cheyyam",
    "cheyyande",
    "cheyyanam",
    "parayatte",
    "parayu",
    "venam",
    "venda",
    "sugam",
    "orma",
    "vecholu",
    "kollam",
    "pinne",
    "kazhinju",
    "undo",
    "ille",
    "pattumo",
    "mathi",
    "oru",
    "ith",
    "athu",
    "ithu",
}

# High-confidence local phrases are the first layer of the student. Teacher
# lessons learned later are stored in SQLite and become another local layer.
LOCAL_MANGGLISH_PHRASES = {
    "nammal ippo entha cheyyande": (
        "നമ്മൾ ഇപ്പോൾ എന്താ ചെയ്യേണ്ടത്?",
        "What should we do now?",
    ),
    "sugam ahno": (
        "സുഖമാണോ?",
        "How are you?",
    ),
    "sugam aano": (
        "സുഖമാണോ?",
        "How are you?",
    ),
    "ente favourite color entha": (
        "എന്റെ ഇഷ്ട നിറം എന്താണ്?",
        "What is my favorite color?",
    ),
    "ente favorite color entha": (
        "എന്റെ ഇഷ്ട നിറം എന്താണ്?",
        "What is my favorite color?",
    ),
    "ith orma vecholu": (
        "ഇത് ഓർമ്മ വെച്ചോളൂ.",
        "Remember this.",
    ),
}


@dataclass
class LanguageResult:
    original: str
    detected_language: str
    normalized_malayalam: str | None = None
    meaning_english: str | None = None
    confidence: float = 0.0
    provider: str = "local"

    def model_text(self):
        if self.detected_language != "manglish":
            return self.original

        parts = [
            "The user wrote Manglish: Malayalam spoken language written using Latin letters.",
            f"Original Manglish: {self.original}",
        ]

        if self.normalized_malayalam:
            parts.append(f"Normalized Malayalam: {self.normalized_malayalam}")

        if self.meaning_english:
            parts.append(f"English meaning: {self.meaning_english}")

        parts.append(
            "Answer the intended meaning, not the wording. Reply naturally in Manglish unless the user asks for another language."
        )
        return "\n".join(parts)


def detect_language(text):
    if MALAYALAM_RE.search(text):
        return "malayalam"

    tokens = [token.lower() for token in WORD_RE.findall(text)]

    if not tokens:
        return "unknown"

    hint_count = sum(1 for token in tokens if token in MANGGLISH_HINTS)

    distinctive = {
        "entha",
        "ente",
        "njan",
        "njn",
        "aanu",
        "aano",
        "ahno",
        "sugam",
        "cheyyande",
        "parayatte",
        "vecholu",
    }

    if hint_count >= 2 or any(token in distinctive for token in tokens):
        return "manglish"

    return "english"


def _phrase_key(text):
    words = WORD_RE.findall(text.lower())
    return " ".join(words)


def _local_phrase_normalize(text):
    match = LOCAL_MANGGLISH_PHRASES.get(_phrase_key(text))

    if not match:
        return None

    normalized_malayalam, meaning_english = match
    return LanguageResult(
        original=text,
        detected_language="manglish",
        normalized_malayalam=normalized_malayalam,
        meaning_english=meaning_english,
        confidence=0.99,
        provider="student:local-phrase",
    )


def _student_fallback(text):
    return LanguageResult(
        original=text,
        detected_language="manglish",
        confidence=0.45,
        provider="student:local-fallback",
    )


def _learned_teacher_result(text):
    learned = get_teacher_example(text)

    if not learned:
        return None

    return LanguageResult(
        original=text,
        detected_language=learned["detected_language"],
        normalized_malayalam=learned["normalized_malayalam"],
        meaning_english=learned["meaning_english"],
        confidence=learned["confidence"],
        provider=f"student:learned:{learned['provider']}",
    )


def _legacy_cached_result(text):
    cached = get_language_cache(text)

    if not cached or not cached["provider"].startswith("gemini:"):
        return None

    # Migrate an older Gemini cache entry into the explicit teacher dataset so
    # future uses count as student-learned examples.
    save_teacher_example(
        source_text=text,
        detected_language=cached["detected_language"],
        student_confidence=0.45,
        teacher_normalized_malayalam=cached["normalized_malayalam"],
        teacher_meaning_english=cached["meaning_english"],
        teacher_confidence=cached["confidence"],
        teacher_provider=cached["provider"],
        lesson="Migrated from legacy Gemini language cache.",
    )

    return LanguageResult(
        original=text,
        detected_language=cached["detected_language"],
        normalized_malayalam=cached["normalized_malayalam"],
        meaning_english=cached["meaning_english"],
        confidence=cached["confidence"],
        provider=f"student:learned:{cached['provider']}",
    )


def _ask_teacher(text, student_result):
    if not teacher_available():
        return None

    student_guess = {
        "normalized_malayalam": student_result.normalized_malayalam,
        "meaning_english": student_result.meaning_english,
        "confidence": student_result.confidence,
        "provider": student_result.provider,
    }

    teacher = normalize_manglish(text, student_guess=student_guess)

    if not teacher:
        return None

    # Low-confidence teacher output is not allowed to become persistent student
    # knowledge. The raw student fallback remains available instead.
    if teacher["confidence"] < 0.70:
        return None

    save_teacher_example(
        source_text=text,
        detected_language="manglish",
        student_normalized_malayalam=student_result.normalized_malayalam,
        student_meaning_english=student_result.meaning_english,
        student_confidence=student_result.confidence,
        teacher_normalized_malayalam=teacher["normalized_malayalam"],
        teacher_meaning_english=teacher["meaning_english"],
        teacher_confidence=teacher["confidence"],
        teacher_provider=teacher["provider"],
        lesson=teacher["lesson"],
    )

    # Keep the old cache populated for backwards compatibility with earlier
    # NEXA builds while teacher_examples becomes the source of learned lessons.
    save_language_cache(
        source_text=text,
        detected_language="manglish",
        normalized_malayalam=teacher["normalized_malayalam"],
        meaning_english=teacher["meaning_english"],
        confidence=teacher["confidence"],
        provider=teacher["provider"],
    )

    return LanguageResult(
        original=text,
        detected_language="manglish",
        normalized_malayalam=teacher["normalized_malayalam"],
        meaning_english=teacher["meaning_english"],
        confidence=teacher["confidence"],
        provider=f"teacher:{teacher['provider']}",
    )


def prepare_user_input(text):
    detected = detect_language(text)

    if detected != "manglish":
        return LanguageResult(
            original=text,
            detected_language=detected,
            confidence=1.0,
            provider="student:local-detector",
        )

    # STUDENT STEP 1: deterministic high-confidence local knowledge.
    local_result = _local_phrase_normalize(text)
    if local_result:
        return local_result

    # STUDENT STEP 2: lessons previously taught by Gemini. This is local SQLite
    # retrieval, so repeated phrases no longer need a Gemini API call.
    learned_result = _learned_teacher_result(text)
    if learned_result:
        return learned_result

    # Backwards-compatible migration path for lessons from the old cache.
    legacy_result = _legacy_cached_result(text)
    if legacy_result:
        return legacy_result

    # STUDENT STEP 3: safe low-confidence fallback. We deliberately do not invent
    # a transliteration when the local system does not know the phrase.
    student_result = _student_fallback(text)

    # TEACHER STEP: only unseen/unknown Manglish reaches Gemini. A trusted lesson
    # is saved to SQLite and becomes local student knowledge on the next use.
    try:
        teacher_result = _ask_teacher(text, student_result)
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
        teacher_result = None

    return teacher_result or student_result
