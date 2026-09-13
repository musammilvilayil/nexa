from __future__ import annotations

import os
import re
from typing import Any, Mapping


class ConversationalEngine:
    """Conversational AI engine for NEXA.
    
    Integrates Gemini, local Ollama, 10-layer memory, and safe local fallbacks.
    """

    SYSTEM_PROMPT = (
        "You are NEXA, an autonomous Level 5 AI operating system and personal assistant. "
        "You are capable, precise, helpful, and polite. Keep conversational answers concise, "
        "informative, and natural. Do not mention that you cannot interact with a computer, "
        "because NEXA has real computer-use automation capabilities."
    )

    def __init__(self) -> None:
        self._gemini_model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self._ollama_model = os.getenv("OLLAMA_MODEL", "qwen3:1.7b")

    def generate_response(self, text: str, *, history: list[dict[str, str]] | None = None) -> str:
        clean = text.strip()
        if not clean:
            return "How can I help you?"

        # 1. First check memory facts
        try:
            from memory import extract_fact, set_fact, identify_fact_query, get_fact, resolve_fact_query
            new_fact = extract_fact(clean)
            if new_fact:
                k, v = new_fact
                set_fact(k, v)
                return f"Got it, I will remember: {k} = {v}"

            fact_key = identify_fact_query(clean)
            if fact_key:
                val = get_fact(fact_key)
                if val is not None:
                    return f"According to my memory, your {fact_key} is {val}."
                return f"I do not know your {fact_key} yet."

            fact = resolve_fact_query(clean)
            if fact:
                _, val = fact
                return val
        except Exception:
            pass

        # 2. Try Gemini if configured
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if api_key:
            try:
                import httpx
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._gemini_model}:generateContent"
                contents = []
                if history:
                    for msg in history[-5:]:
                        role = "model" if msg.get("role") == "assistant" else "user"
                        contents.append({"role": role, "parts": [{"text": msg.get("content", "")}]})
                contents.append({"role": "user", "parts": [{"text": clean}]})
                
                resp = httpx.post(
                    url,
                    headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                    json={
                        "systemInstruction": {"parts": [{"text": self.SYSTEM_PROMPT}]},
                        "contents": contents,
                    },
                    timeout=8.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        ans = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
                        if ans:
                            return ans
            except Exception:
                pass

        # 3. Try Ollama if running
        try:
            from bridges.ollama_bridge import OllamaBridge
            bridge = OllamaBridge(model=self._ollama_model, timeout=4.0)
            if bridge.is_available():
                messages = [{"role": "system", "content": self.SYSTEM_PROMPT}]
                if history:
                    for msg in history[-5:]:
                        role = msg.get("role", "user")
                        if role in {"user", "assistant"}:
                            messages.append({"role": role, "content": msg.get("content", "")})
                messages.append({"role": "user", "content": clean})
                res = bridge.chat(messages)
                if isinstance(res, str) and res.strip():
                    return res.strip()
        except Exception:
            pass

        # 4. Safe rule-based conversational fallback
        return self._rule_based_reply(clean)

    def _rule_based_reply(self, text: str) -> str:
        low = text.lower().strip().rstrip(".!?")
        if re.search(r"^(?:hey|hi|hello|greetings)(?:\s+|$)", low):
            return "Hello! I am NEXA, your Level 5 Autonomous AI OS. How can I assist you today?"
        if "how are you" in low:
            return "I am functioning optimally with all security controls, monitors, and skills active. How can I assist you?"
        if "who are you" in low or "what are you" in low or "what is your name" in low:
            return "I am NEXA (Autonomous AI OS), an autonomous agent operating system capable of executing computer tasks, managing applications, and assisting with complex workflows."
        if re.search(r" can you ", low):
            return "Yes, I can execute desktop actions, open applications, search the web, type text, manage files, and automate multi-step tasks. What would you like me to do?"
        if "thank you" in low or "thanks" in low:
            return "You're very welcome! Let me know whenever you have more tasks."
        if "tell me a joke" in low:
            return "Why do programmers prefer dark mode? Because light attracts bugs!"
        return f"I understand your query: '{text}'. I am ready to help you with desktop automation, research, or answering questions."
