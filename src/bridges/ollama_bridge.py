from __future__ import annotations

import json
import os
from typing import Any, Mapping

import httpx


class OllamaBridgeError(RuntimeError):
    pass


class OllamaBridge:
    """Small local-model bridge using Ollama's non-streaming chat API."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
        self.model = (model or os.getenv("OLLAMA_MODEL") or "qwen3:1.7b").strip()
        if not self.model:
            raise ValueError("Ollama model cannot be empty")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = float(timeout)

    def chat(
        self,
        messages: list[Mapping[str, str]],
        *,
        schema: Mapping[str, Any] | None = None,
        think: bool = False,
    ) -> str | dict[str, Any]:
        if not messages:
            raise OllamaBridgeError("messages cannot be empty")
        normalized = []
        for message in messages:
            role = str(message.get("role", "")).strip()
            content = str(message.get("content", "")).strip()
            if role not in {"system", "user", "assistant"} or not content:
                raise OllamaBridgeError("invalid chat message")
            normalized.append({"role": role, "content": content})

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": normalized,
            "stream": False,
            "think": think,
        }
        if schema is not None:
            payload["format"] = dict(schema)

        try:
            response = httpx.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
            content = data["message"]["content"]
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise OllamaBridgeError(f"Ollama chat failed: {exc}") from exc

        if not isinstance(content, str):
            raise OllamaBridgeError("Ollama response content is not text")
        content = content.strip()
        if schema is None:
            return content
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaBridgeError("Ollama structured response is not valid JSON") from exc
        if not isinstance(parsed, dict):
            raise OllamaBridgeError("Ollama structured response must be a JSON object")
        return parsed
