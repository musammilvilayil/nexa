from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping

import httpx


class GeminiBridgeError(RuntimeError):
    pass


class GeminiBridge:
    """Secret-safe Gemini JSON bridge for teacher/reviewer roles.

    The API key is read from GEMINI_API_KEY at call time and is never stored on
    the object, returned in results, or passed to audit parameters.
    """

    API_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def __init__(
        self,
        *,
        model: str | None = None,
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        self.model = (model or os.getenv("GEMINI_MODEL") or "gemini-3.6-flash").strip()
        if not self.model:
            raise ValueError("Gemini model cannot be empty")
        if timeout <= 0 or max_retries < 0:
            raise ValueError("invalid Gemini bridge limits")
        self.timeout = float(timeout)
        self.max_retries = int(max_retries)

    def available(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY", "").strip())

    def generate_json(
        self,
        prompt: str,
        schema: Mapping[str, Any],
        *,
        system_instruction: str | None = None,
    ) -> dict[str, Any]:
        if not prompt.strip():
            raise GeminiBridgeError("prompt cannot be empty")
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise GeminiBridgeError("GEMINI_API_KEY is not available")

        base_payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        }
        if system_instruction and system_instruction.strip():
            base_payload["systemInstruction"] = {
                "parts": [{"text": system_instruction.strip()}]
            }

        modern_config = {
            "responseFormat": {
                "text": {
                    "mimeType": "application/json",
                    "schema": dict(schema),
                }
            }
        }
        legacy_config = {
            "responseMimeType": "application/json",
            "responseSchema": dict(schema),
        }

        last_error: Exception | None = None
        for config in (modern_config, legacy_config):
            payload = dict(base_payload)
            payload["generationConfig"] = config
            try:
                data = self._request(payload, api_key)
                text = self._extract_text(data)
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise GeminiBridgeError("Gemini structured response must be a JSON object")
                _validate_schema(parsed, schema)
                return parsed
            except httpx.HTTPStatusError as exc:
                last_error = exc
                if exc.response.status_code != 400:
                    raise GeminiBridgeError(
                        f"Gemini API returned HTTP {exc.response.status_code}"
                    ) from exc
            except (json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError) as exc:
                raise GeminiBridgeError(f"Gemini returned invalid structured output: {exc}") from exc

        raise GeminiBridgeError(f"Gemini structured output request failed: {last_error}")

    def _request(self, payload: Mapping[str, Any], api_key: str) -> dict[str, Any]:
        url = self.API_TEMPLATE.format(model=self.model)
        for attempt in range(self.max_retries + 1):
            try:
                response = httpx.post(
                    url,
                    headers={
                        "x-goog-api-key": api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict):
                    raise GeminiBridgeError("Gemini API returned a non-object response")
                return data
            except httpx.HTTPStatusError as exc:
                retryable = exc.response.status_code == 429 or exc.response.status_code >= 500
                if not retryable or attempt >= self.max_retries:
                    raise
                time.sleep(min(4.0, 0.5 * (2**attempt)))
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt >= self.max_retries:
                    raise GeminiBridgeError(f"Gemini network request failed: {exc}") from exc
                time.sleep(min(4.0, 0.5 * (2**attempt)))
        raise GeminiBridgeError("Gemini request retry loop exhausted")

    @staticmethod
    def _extract_text(payload: Mapping[str, Any]) -> str:
        candidates = payload.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            feedback = payload.get("promptFeedback")
            raise GeminiBridgeError(f"Gemini returned no candidates; feedback={feedback!r}")
        parts = candidates[0]["content"]["parts"]
        texts = [part.get("text", "") for part in parts if isinstance(part, dict)]
        text = "".join(texts).strip()
        if not text:
            raise GeminiBridgeError("Gemini candidate contained no text")
        return text


def _validate_schema(value: Any, schema: Mapping[str, Any], path: str = "$") -> None:
    expected = schema.get("type")
    if isinstance(expected, list):
        if value is None and "null" in expected:
            return
        non_null = [item for item in expected if item != "null"]
        if len(non_null) == 1:
            expected = non_null[0]

    if isinstance(expected, str):
        expected = expected.lower()

    if expected == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object")
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ValueError(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        if isinstance(properties, Mapping):
            for key, child_schema in properties.items():
                if key in value and isinstance(child_schema, Mapping):
                    _validate_schema(value[key], child_schema, f"{path}.{key}")
        return

    if expected == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(value):
                _validate_schema(item, item_schema, f"{path}[{index}]")
        return

    if expected == "string" and not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    if expected == "boolean" and not isinstance(value, bool):
        raise ValueError(f"{path} must be a boolean")
    if expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValueError(f"{path} must be an integer")
    if expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise ValueError(f"{path} must be a number")

    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path} is not an allowed enum value")
