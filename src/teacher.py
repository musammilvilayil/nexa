import json
import os
import re

import httpx

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
DEFAULT_GEMINI_MODEL = "gemini-3.6-flash"


def teacher_available():
    return bool(os.getenv("GEMINI_API_KEY", "").strip())


def _parse_json_text(text):
    clean = text.strip()

    if clean.startswith("```"):
        clean = re.sub(r"^```(?:json)?\s*", "", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s*```$", "", clean)

    start = clean.find("{")
    end = clean.rfind("}")

    if start == -1 or end == -1 or end <= start:
        raise ValueError("Gemini teacher did not return a JSON object")

    return json.loads(clean[start : end + 1])


def normalize_manglish(text, student_guess=None):
    """Ask Gemini to act as a teacher for one Manglish utterance.

    This function does not write memory. The caller decides whether the lesson
    is trustworthy enough to persist as student training data.
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if not api_key:
        return None

    model = os.getenv("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip()
    url = GEMINI_API_URL.format(model=model)

    student_block = "No confident local interpretation was available."
    if student_guess:
        student_block = json.dumps(student_guess, ensure_ascii=False)

    prompt = f"""
You are the TEACHER language model for NEXA, a local personal AI assistant.
The STUDENT is a small local model that needs help understanding Malayalam
written in Latin letters (Manglish), including spelling variation,
abbreviations, slang, and English code-switching.

User input:
{text}

Student's current interpretation:
{student_block}

Your job:
1. Decide whether the input is Manglish.
2. Preserve the exact intended meaning. Do not invent personal facts or context.
3. If Manglish, produce natural Malayalam-script normalization.
4. Produce a concise English meaning for downstream reasoning.
5. Give confidence from 0.0 to 1.0.
6. Briefly explain what the student should learn from this example.

Return ONLY valid JSON in this exact shape:
{{
  "is_manglish": true,
  "normalized_malayalam": "...",
  "meaning_english": "...",
  "confidence": 0.0,
  "lesson": "..."
}}
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

    return {
        "normalized_malayalam": (
            (parsed.get("normalized_malayalam") or "").strip() or None
        ),
        "meaning_english": (parsed.get("meaning_english") or "").strip() or None,
        "confidence": confidence,
        "lesson": (parsed.get("lesson") or "").strip() or None,
        "provider": f"gemini:{model}",
    }
