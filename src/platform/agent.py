from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from .runtime import AgentSession, SessionManager, SessionState
from .tools import ToolRegistry, build_default_registry


@dataclass
class AgentReply:
    session_id: str
    message: str
    tool_calls: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]


class NexaAgent:
    """Chat-first execution facade over NEXA capabilities.

    This deterministic foundation keeps execution inspectable. LLM planning can be
    plugged in above plan() without changing tool/session contracts.
    """

    def __init__(self, registry: ToolRegistry | None = None, sessions: SessionManager | None = None) -> None:
        self.registry = registry or build_default_registry()
        self.sessions = sessions or SessionManager()

    def new_session(self) -> AgentSession:
        session = self.sessions.create()
        return self.sessions.transition(session, SessionState.RUNNING)

    def chat(self, message: str, session_id: str | None = None) -> AgentReply:
        session = self.sessions.load(session_id) if session_id else self.new_session()
        if session.state == SessionState.SUSPENDED:
            self.sessions.transition(session, SessionState.RUNNING)
        if session.state != SessionState.RUNNING:
            raise ValueError("session is not running")
        session.add_message("user", message)
        calls = self.plan(message)
        outputs = []
        for call in calls:
            result = self.registry.call(call["tool"], call.get("params"))
            outputs.append({"tool": call["tool"], "success": result.success, "data": result.data, "error": result.error})
        reply = self._summarize(message, outputs)
        session.add_message("assistant", reply, tool_calls=outputs)
        self.sessions.save(session)
        return AgentReply(session.id, reply, outputs, session.artifacts)

    def plan(self, message: str) -> list[dict[str, Any]]:
        text = message.strip()
        lower = text.lower()
        if lower in {"tools", "show tools", "what can you do"}:
            return []
        match = re.match(r"(?:read|open)\s+(.+)$", text, re.I)
        if match:
            return [{"tool": "workspace.read", "params": {"path": match.group(1).strip()}}]
        match = re.match(r"(?:save|write)\s+(.+?)\s*::\s*(.*)$", text, re.I | re.S)
        if match:
            return [{"tool": "workspace.write", "params": {"path": match.group(1).strip(), "content": match.group(2)}}]
        return []

    def _summarize(self, message: str, outputs: list[dict[str, Any]]) -> str:
        if message.strip().lower() in {"tools", "show tools", "what can you do"}:
            return "Available tools: " + ", ".join(item["name"] for item in self.registry.catalog())
        if not outputs:
            return "I understood the request, but no executable tool plan matched yet. Connect an LLM planner or use 'show tools'."
        failed = [x for x in outputs if not x["success"]]
        if failed:
            return "I attempted the task, but a tool failed: " + "; ".join(x["error"] or "unknown error" for x in failed)
        return f"Completed {len(outputs)} tool action(s) successfully."
