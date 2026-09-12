from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class IntentType(str, Enum):
    CHAT = "chat"
    INFORMATION = "information"
    AGENT_TASK = "agent_task"
    MIXED = "mixed"
    VOICE_COMMAND = "voice_command"
    CLARIFICATION = "clarification"


@dataclass(frozen=True)
class IntentClassification:
    intent_type: IntentType
    confidence: float
    action_prompt: str = ""
    chat_prompt: str = ""
    entities: dict[str, Any] = field(default_factory=dict)
    raw_text: str = ""


class IntentRouter:
    """Canonical intent classifier for NEXA Level 5+."""

    ACTION_VERBS = (
        "open", "launch", "start", "run", "execute", "type", "click", "press",
        "scroll", "close", "kill", "quit", "exit", "screenshot", "capture",
        "search", "navigate", "browse", "visit", "download", "upload",
        "copy", "paste", "move", "rename", "delete", "create", "make",
        "read", "find", "save", "check", "verify", "write", "append",
        "mkdir", "focus", "list", "inspect", "locate", "analyze",
        "audit", "backup", "show status", "system status", "status",
        "buy", "sell", "trade", "portfolio", "balance",
    )

    CHAT_PATTERNS = (
        r"^(?:hey|hi|hello|greetings|howdy|sup)\b",
        r"\bhow are you\b",
        r"\bwho are you\b",
        r"\bwhat is your name\b",
        r"\bcan you\s*$",
        r"\bcan you hear me\b",
        r"\btell me a joke\b",
        r"\bthank you\b",
        r"\bthanks\b",
        r"\bgood (?:morning|afternoon|evening|night)\b",
        r"^(?:njan|entha|sugam|kollam|mathi)\b",
    )

    INFO_PATTERNS = (
        r"^(?:what is|what are|what's|who is|who was)\b",
        r"^(?:explain|describe|tell me about|how does|why does|why is)\b",
        r"^(?:how to|how do I|how can I)\b",
        r"^(?:write a poem|write code|give me an example)\b",
    )

    MIXED_PATTERNS = (
        re.compile(r"^(?P<info>what is|explain|tell me about)\s+(?P<topic>.+?)\s+(?:and|then)\s+(?P<action>open|launch|search|browse|go to)\s+(?P<target>.+)$", re.IGNORECASE),
    )

    def __init__(self) -> None:
        self._action_verb_re = re.compile(
            r"^(?:" + "|".join(re.escape(v) for v in self.ACTION_VERBS) + r")\b",
            re.IGNORECASE,
        )
        self._chat_res = [re.compile(p, re.IGNORECASE) for p in self.CHAT_PATTERNS]
        self._info_res = [re.compile(p, re.IGNORECASE) for p in self.INFO_PATTERNS]

    def classify(self, text: str) -> IntentClassification:
        clean = text.strip()
        if not clean:
            return IntentClassification(
                intent_type=IntentType.CHAT,
                confidence=1.0,
                chat_prompt="",
                raw_text="",
            )

        # 1. Check MIXED intent (e.g. 'what is Upwork and open it')
        for mixed_re in self.MIXED_PATTERNS:
            match = mixed_re.match(clean)
            if match:
                groups = match.groupdict()
                info_part = f"{groups.get('info', 'what is')} {groups.get('topic', '')}".strip()
                action_part = f"{groups.get('action', 'open')} {groups.get('target', '')}".strip()
                return IntentClassification(
                    intent_type=IntentType.MIXED,
                    confidence=0.95,
                    action_prompt=action_part,
                    chat_prompt=info_part,
                    entities={"topic": groups.get("topic", ""), "target": groups.get("target", "")},
                    raw_text=clean,
                )

        # 2. Check conversational CHAT patterns
        for chat_re in self._chat_res:
            if chat_re.search(clean):
                from core.entity_resolver import EntityResolver
                stripped = EntityResolver.strip_politeness(clean)
                if self._action_verb_re.search(stripped):
                    return IntentClassification(
                        intent_type=IntentType.AGENT_TASK,
                        confidence=0.9,
                        action_prompt=stripped,
                        raw_text=clean,
                    )
                return IntentClassification(
                    intent_type=IntentType.CHAT,
                    confidence=0.95,
                    chat_prompt=clean,
                    raw_text=clean,
                )

        # 3. Check INFORMATION query patterns
        for info_re in self._info_res:
            if info_re.search(clean):
                return IntentClassification(
                    intent_type=IntentType.INFORMATION,
                    confidence=0.92,
                    chat_prompt=clean,
                    raw_text=clean,
                )

        # 4. Check ACTION / AGENT_TASK patterns
        from core.entity_resolver import EntityResolver
        stripped = EntityResolver.strip_politeness(clean)
        if self._action_verb_re.search(clean) or self._action_verb_re.search(stripped):
            return IntentClassification(
                intent_type=IntentType.AGENT_TASK,
                confidence=0.95,
                action_prompt=stripped,
                raw_text=clean,
            )

        # Check secondary action indicators
        lower = clean.lower()
        if any(w in lower for w in (
            "open", "type", "click", "search", "notepad", "calculator", "browser",
            "terminal", "audit", "status", "folder", "directory", "file", "download",
            "archive", "create", "delete", "write", "read", "move", "copy", "verify",
            "analyze", "storage", "disk", "drive", "drives"
        )):
            return IntentClassification(
                intent_type=IntentType.AGENT_TASK,
                confidence=0.85,
                action_prompt=clean,
                raw_text=clean,
            )

        # 5. Default fallback: Conversational CHAT
        return IntentClassification(
            intent_type=IntentType.CHAT,
            confidence=0.7,
            chat_prompt=clean,
            raw_text=clean,
        )
