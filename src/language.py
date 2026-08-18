import json
import os
import re
from dataclasses import dataclass

import httpx

from memory import get_language_cache, save_language_cache

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"

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

# High-confidence local phrases. This gives the small local model clean intent
# even when Gemini is unavailable. We will later replace/expand this with a
# proper transliteration model and learned correction dataset.
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
        provider="local-phrase",
    )


def _parse_json_text(text):
    clean = text.strip()

    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)

    start = clean.find("{")
    end = clean.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("Gemini did not return a JSON object")

    return json.loads(clean[start : end + 1])


def _gemini_normalize(text):
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        return None

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    url = GEMINI_API_URL.format(model=model)

    prompt = f"""
You are the language-normalization layer for NEXA.
The user may write Malayalam using Latin letters (Manglish), with spelling variations, abbreviations, and English code-switching.

Task:
1. Decide whether the input is Manglish.
2. Preserve the exact intended meaning; do not invent facts.
3. If it is Manglish, write a natural Malayalam-script normalization.
4. Give a concise English meaning for downstream reasoning.
5. Return a confidence from 0.0 to 1.0.

Return ONLY this JSON shape:
{{
  "is_manglish": true,
  "normalized_malayalam": "...",
  "meaning_english": "...",
  "confidence": 0.0
}}

Input:
{text}
""".strip()

    response = httpx.post(
        url,
        headers={
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        },
        json={
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                    ]
                }
            ]
        },
        timeout=30,
    )
    response.raise_for_status()

    payload = response.json()
    output_text = payload["candidates"][0]["content"]["parts"][0]["text"]
    parsed = _parse_json_text(output_text)

    if not parsed.get("is_manglish", False):
        return None

    confidence = parsed.get("confidence", 0.0)

    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))

    return LanguageResult(
        original=text,
        detected_language="manglish",
        normalized_malayalam=(parsed.get("normalized_malayalam") or "").strip() or None,
        meaning_english=(parsed.get("meaning_english") or "").strip() or None,
        confidence=confidence,
        provider=f"gemini:{model}",
    )


def prepare_user_input(text):
    detected = detect_language(text)

    if detected != "manglish":
        return LanguageResult(
            original=text,
            detected_language=detected,
            confidence=1.0,
            provider="local-detector",
        )

    # Use deterministic local interpretations first when we know the phrase.
    local_result = _local_phrase_normalize(text)
    if local_result:
        return local_result

    cached = get_language_cache(text)

    if cached and cached["provider"].startswith("gemini:"):
        return LanguageResult(
            original=text,
            detected_language=cached["detected_language"],
            normalized_malayalam=cached["normalized_malayalam"],
            meaning_english=cached["meaning_english"],
            confidence=cached["confidence"],
            provider=f"cache:{cached['provider']}",
        )

    try:
        result = _gemini_normalize(text)
    except (httpx.HTTPError, KeyError, ValueError, json.JSONDecodeError):
        result = None

    if result:
        save_language_cache(
            source_text=text,
            detected_language=result.detected_language,
            normalized_malayalam=result.normalized_malayalam,
            meaning_english=result.meaning_english,
            confidence=result.confidence,
            provider=result.provider,
        )
        return result

    # Safe local fallback: preserve raw text and clearly tell the local model that
    # this is Manglish instead of inventing a low-confidence transliteration.
    return LanguageResult(
        original=text,
        detected_language="manglish",
        confidence=0.45,
        provider="local-fallback",
    )
