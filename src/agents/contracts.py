from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping
from uuid import uuid4

from core.contracts import RiskTier


class AgentRole(str, Enum):
    SUPERVISOR = "supervisor"
    PLANNER = "planner"
    RESEARCH = "research"
    BROWSER = "browser"
    DESKTOP = "desktop"
    CODER = "coder"
    VERIFIER = "verifier"
    SECURITY = "security"


class AgentStatus(str, Enum):
    IDLE = "idle"
    BUSY = "busy"
    WAITING = "waiting"
    DONE = "done"
    FAILED = "failed"


@dataclass(frozen=True)
class AgentMessage:
    sender: AgentRole
    receiver: AgentRole
    content: str
    data: dict[str, Any] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: uuid4().hex[:8])
    timestamp: float = field(default_factory=time.time)


@dataclass
class AgentDelegation:
    from_agent: AgentRole
    to_agent: AgentRole
    instruction: str
    params: dict[str, Any] = field(default_factory=dict)
    max_risk: RiskTier = RiskTier.MUTATE
    timeout_seconds: float = 30.0
    status: AgentStatus = AgentStatus.WAITING
    result: Any = None
    error: str | None = None
    delegation_id: str = field(default_factory=lambda: uuid4().hex[:8])
    created_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class AgentResult:
    success: bool
    output: str
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    role: AgentRole = AgentRole.SUPERVISOR
