from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class SessionState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    SUSPENDED = "suspended"
    STOPPED = "stopped"


@dataclass
class AgentSession:
    id: str
    state: SessionState = SessionState.CREATED
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    messages: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    def add_message(self, role: str, content: str, **metadata: Any) -> None:
        self.messages.append({"role": role, "content": content, "metadata": metadata})


class SessionManager:
    """Small local actor lifecycle; replaceable later by gVisor/microVM backends."""

    def __init__(self, state_dir: str | Path = ".nexa/sessions") -> None:
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def create(self) -> AgentSession:
        session = AgentSession(id=uuid.uuid4().hex)
        self.save(session)
        return session

    def load(self, session_id: str) -> AgentSession:
        data = json.loads((self.state_dir / f"{session_id}.json").read_text(encoding="utf-8"))
        data["state"] = SessionState(data["state"])
        return AgentSession(**data)

    def save(self, session: AgentSession) -> None:
        payload = asdict(session)
        payload["state"] = session.state.value
        (self.state_dir / f"{session.id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def transition(self, session: AgentSession, state: SessionState) -> AgentSession:
        allowed = {
            SessionState.CREATED: {SessionState.RUNNING, SessionState.STOPPED},
            SessionState.RUNNING: {SessionState.SUSPENDED, SessionState.STOPPED},
            SessionState.SUSPENDED: {SessionState.RUNNING, SessionState.STOPPED},
            SessionState.STOPPED: set(),
        }
        if state not in allowed[session.state]:
            raise ValueError(f"invalid session transition: {session.state.value} -> {state.value}")
        session.state = state
        self.save(session)
        return session
