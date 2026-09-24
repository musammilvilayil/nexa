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
    """Chat-first NEXA agent with inspectable tool execution and optional LLM planning."""

    def __init__(self, registry: ToolRegistry | None = None, sessions: SessionManager | None = None) -> None:
        self.registry = registry or build_default_registry()
        self.sessions = sessions or SessionManager()

    def new_session(self) -> AgentSession:
        return self.sessions.transition(self.sessions.create(), SessionState.RUNNING)

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
        # Prefer structured Gemini planning when configured, but keep NEXA useful offline.
        try:
            from bridges.gemini_bridge import GeminiBridge
            bridge = GeminiBridge()
            if bridge.available():
                catalog = self.registry.catalog()
                names = [item["name"] for item in catalog]
                schema = {"type":"object","required":["calls"],"properties":{"calls":{"type":"array","items":{"type":"object","required":["tool","params"],"properties":{"tool":{"type":"string"},"params":{"type":"object"}}}}}}
                prompt = "User request: " + message + "\nAvailable tools: " + ", ".join(names) + "\nReturn only necessary tool calls. Never invent a tool. For conversation that needs no tool return an empty calls array."
                planned = bridge.generate_json(prompt, schema, system_instruction="You are NEXA's tool planner. Choose the minimum safe tool calls from the supplied catalog.")
                calls = planned.get("calls", [])
                valid = set(names)
                return [c for c in calls if isinstance(c, dict) and c.get("tool") in valid and isinstance(c.get("params"), dict)]
        except Exception:
            pass

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
            return "I can handle this as a conversation, but this build currently executes tasks only when a registered tool is required."
        failed = [x for x in outputs if not x["success"]]
        if failed:
            return "I attempted the task, but a tool failed: " + "; ".join(x["error"] or "unknown error" for x in failed)
        details = [str(x.get("data")) for x in outputs if x.get("data") is not None]
        return "Completed successfully." + (("\n\n" + "\n".join(details)) if details else "")
