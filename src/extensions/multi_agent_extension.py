from __future__ import annotations

import threading
from typing import Any, Mapping

from core.security import SecurityGate
from extensions.contracts import ExtensionStatus, LifecycleExtension
from agents.contracts import AgentRole
from agents.orchestrator import SupervisorOrchestrator


class MultiAgentExtension(LifecycleExtension):
    """Extension managing hierarchical multi-agent collaboration with strict security boundaries."""

    def __init__(self, security_gate: SecurityGate | None = None) -> None:
        self.security_gate = security_gate
        self.orchestrator = SupervisorOrchestrator(security_gate=security_gate)
        self._status = ExtensionStatus.DISCOVERED
        self._lock = threading.Lock()

    def initialize(self) -> bool:
        with self._lock:
            self._status = ExtensionStatus.ACTIVE
            return True

    def shutdown(self) -> bool:
        with self._lock:
            self._status = ExtensionStatus.STOPPED
            return True

    def health_check(self) -> dict[str, Any]:
        with self._lock:
            workers = self.orchestrator.list_workers()
            return {
                "healthy": self._status == ExtensionStatus.ACTIVE,
                "status": self._status.value,
                "worker_count": len(workers),
                "workers": [w["role"] for w in workers],
            }

    def is_available(self) -> bool:
        return self._status in (ExtensionStatus.ACTIVE, ExtensionStatus.INITIALIZED)

    def orchestrate(self, goal: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        res = self.orchestrator.orchestrate(goal, context)
        return {
            "success": res.success,
            "output": res.output,
            "data": res.data,
            "error": res.error,
        }

    def list_agents(self) -> list[dict[str, Any]]:
        return self.orchestrator.list_workers()
