from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import httpx

GEMINI_API_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "{model}:generateContent"
)
DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"


class GeminiAgentError(RuntimeError):
    pass


@dataclass(frozen=True)
class GeminiDecision:
    answer: str
    tool: str | None = None
    args: Mapping[str, Any] = None
    requires_confirmation: bool = False

    def __post_init__(self):
        if self.args is None:
            object.__setattr__(self, "args", {})


class GeminiAgent:
    """Gemini reasoning adapter for NEXA's independent agent layer.

    The API key is read only from GEMINI_API_KEY. Model output is parsed as
    structured data and is never executed as shell text.
    """

    def __init__(self, model: str | None = None, timeout: float = 60.0):
        self.model = (model or os.getenv("GEMINI_MODEL") or DEFAULT_GEMINI_MODEL).strip()
        self.timeout = timeout

    @property
    def available(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY", "").strip())

    def decide(self, goal: str, tools: Sequence[Mapping[str, Any]], context: str = "") -> GeminiDecision:
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise GeminiAgentError("GEMINI_API_KEY is not configured")
        if not goal.strip():
            raise GeminiAgentError("Agent goal cannot be empty")

        tool_text = json.dumps(list(tools), ensure_ascii=False)
        prompt = f"""
You are NEXA's reasoning engine. Work as a careful agent, not as an arbitrary shell executor.
Understand the user's goal, choose at most one allow-listed tool, and return ONLY valid JSON.
Never invent tools. Never put shell commands in tool arguments. Mutating actions must require confirmation.

AVAILABLE TOOLS:
{tool_text}

CONTEXT:
{context or 'none'}

USER GOAL:
{goal}

JSON shape:
{{
  "answer": "short explanation of what you will do or the result",
  "tool": null,
  "args": {{}},
  "requires_confirmation": false
}}
""".strip()

        response = httpx.post(
            GEMINI_API_URL.format(model=self.model),
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json={"contents": [{"parts": [{"text": prompt}]}]},
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        try:
            text = payload["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise GeminiAgentError("Gemini returned no usable response") from exc

        clean = text.strip()
        if clean.startswith("```"):
            clean = clean.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            data = json.loads(clean)
        except json.JSONDecodeError as exc:
            raise GeminiAgentError("Gemini agent response was not valid JSON") from exc

        tool = data.get("tool")
        if tool is not None and not isinstance(tool, str):
            raise GeminiAgentError("Gemini returned an invalid tool name")
        args = data.get("args") or {}
        if not isinstance(args, dict):
            raise GeminiAgentError("Gemini returned invalid tool arguments")

        return GeminiDecision(
            answer=str(data.get("answer") or ""),
            tool=tool,
            args=args,
            requires_confirmation=bool(data.get("requires_confirmation", False)),
        )
