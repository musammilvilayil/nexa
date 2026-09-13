from __future__ import annotations

import threading
import time
from typing import Any, Mapping
from uuid import uuid4

from core.contracts import RiskTier
from core.security import SecurityGate
from .contracts import (
    AgentDelegation,
    AgentMessage,
    AgentResult,
    AgentRole,
    AgentStatus,
)
from .workers import (
    BaseWorker,
    BrowserWorker,
    CoderWorker,
    DesktopWorker,
    PlannerWorker,
    ResearchWorker,
    SecurityWorker,
    VerifierWorker,
)


_RISK_HIERARCHY = {
    RiskTier.READ: 1,
    RiskTier.MUTATE: 2,
    RiskTier.REMOTE: 3,
    RiskTier.DESTRUCTIVE: 4,
    RiskTier.CRITICAL: 5,
}


class SupervisorOrchestrator:
    """Supervisor orchestrating multi-agent collaboration with strict security boundaries and privilege checks."""

    def __init__(self, security_gate: SecurityGate | None = None) -> None:
        self.security_gate = security_gate
        self._workers: dict[AgentRole, BaseWorker] = {}
        self._blackboard: dict[str, Any] = {}
        self._messages: list[AgentMessage] = []
        self._delegations: list[AgentDelegation] = []
        self._lock = threading.Lock()

        # Register default specialized workers
        self.register_worker(PlannerWorker())
        self.register_worker(ResearchWorker())
        self.register_worker(BrowserWorker())
        self.register_worker(DesktopWorker())
        self.register_worker(CoderWorker())
        self.register_worker(VerifierWorker())
        self.register_worker(SecurityWorker())

    def register_worker(self, worker: BaseWorker) -> None:
        with self._lock:
            self._workers[worker.role] = worker

    def get_worker(self, role: AgentRole) -> BaseWorker | None:
        with self._lock:
            return self._workers.get(role)

    def list_workers(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "role": w.role.value,
                    "allowed_risk": w.allowed_risk.value,
                    "class": w.__class__.__name__,
                }
                for w in self._workers.values()
            ]

    def read_blackboard(self, key: str | None = None) -> Any:
        with self._lock:
            if key is None:
                return dict(self._blackboard)
            return self._blackboard.get(key)

    def write_blackboard(self, key: str, value: Any) -> None:
        with self._lock:
            self._blackboard[key] = value

    def delegate(
        self,
        from_agent: AgentRole,
        to_agent: AgentRole,
        instruction: str,
        params: dict[str, Any] | None = None,
        max_risk: RiskTier = RiskTier.MUTATE,
        confirmed: bool = False,
    ) -> AgentResult:
        with self._lock:
            target_worker = self._workers.get(to_agent)
            if not target_worker:
                return AgentResult(
                    success=False,
                    output=f"Target agent role '{to_agent.value}' not found",
                    error="agent_not_found",
                    role=AgentRole.SUPERVISOR,
                )

            # 1. Privilege escalation prevention
            if from_agent != AgentRole.SUPERVISOR:
                caller_worker = self._workers.get(from_agent)
                if caller_worker:
                    caller_level = _RISK_HIERARCHY.get(caller_worker.allowed_risk, 1)
                    target_level = _RISK_HIERARCHY.get(target_worker.allowed_risk, 1)
                    requested_level = _RISK_HIERARCHY.get(max_risk, 1)
                    if requested_level > caller_level or target_level > caller_level:
                        return AgentResult(
                            success=False,
                            output=f"Privilege escalation blocked: {from_agent.value} cannot delegate {max_risk.value} to {to_agent.value}",
                            error="privilege_escalation_blocked",
                            role=AgentRole.SUPERVISOR,
                        )

            delegation = AgentDelegation(
                from_agent=from_agent,
                to_agent=to_agent,
                instruction=instruction,
                params=params or {},
                max_risk=max_risk,
                status=AgentStatus.BUSY,
            )

        # 2. Security Gate check
        if self.security_gate:
            deny_decision = self.security_gate.check_deny_list(f"{to_agent.value} {instruction}")
            if deny_decision and deny_decision.outcome.value == "deny":
                with self._lock:
                    delegation.status = AgentStatus.FAILED
                    delegation.error = deny_decision.reason
                    self._delegations.append(delegation)
                return AgentResult(
                    success=False,
                    output=f"SecurityGate denied delegation: {deny_decision.reason}",
                    error=deny_decision.reason,
                    role=to_agent,
                )

            decision = self.security_gate.evaluate(
                skill_name=f"agent_{to_agent.value}",
                operation="delegate",
                params=dict(params or {}),
                risk=max_risk,
                confirmed=confirmed,
            )
            if decision.outcome.value == "deny":
                with self._lock:
                    delegation.status = AgentStatus.FAILED
                    delegation.error = decision.reason
                    self._delegations.append(delegation)
                return AgentResult(
                    success=False,
                    output=f"SecurityGate blocked delegation: {decision.reason}",
                    error=decision.reason,
                    role=to_agent,
                )
            if decision.outcome.value == "require_confirmation":
                with self._lock:
                    delegation.status = AgentStatus.WAITING
                    delegation.error = "confirmation_required"
                    self._delegations.append(delegation)
                return AgentResult(
                    success=False,
                    output=f"Confirmation required for delegation ({decision.reason})",
                    error="confirmation_required",
                    role=to_agent,
                )

        # 3. Worker execution
        try:
            result = target_worker.execute(delegation, self.read_blackboard())
            with self._lock:
                delegation.status = AgentStatus.DONE if result.success else AgentStatus.FAILED
                delegation.result = result.data
                delegation.error = result.error
                self._delegations.append(delegation)

                # Store message exchange
                msg = AgentMessage(
                    sender=from_agent,
                    receiver=to_agent,
                    content=instruction,
                    data={"result": result.output},
                )
                self._messages.append(msg)
                self._blackboard[f"last_{to_agent.value}_result"] = result.data
            return result
        except Exception as exc:
            with self._lock:
                delegation.status = AgentStatus.FAILED
                delegation.error = str(exc)
                self._delegations.append(delegation)
            return AgentResult(
                success=False,
                output=f"Agent execution failed: {exc}",
                error=str(exc),
                role=to_agent,
            )

    def orchestrate(self, goal: str, context: Mapping[str, Any] | None = None) -> AgentResult:
        """Top-level supervisor workflow: plan -> execute subtasks -> verify -> synthesize."""
        # Step 1: Planning
        plan_res = self.delegate(
            AgentRole.SUPERVISOR,
            AgentRole.PLANNER,
            goal,
            max_risk=RiskTier.READ,
        )
        if not plan_res.success:
            return plan_res

        subtasks = plan_res.data.get("subtasks", [])
        collected_outputs = [plan_res.output]

        # Step 2: Delegate subtasks
        for sub in subtasks:
            action_type = sub.get("action", "research")
            target_role = AgentRole.RESEARCH if action_type == "research" else AgentRole.CODER
            sub_res = self.delegate(
                AgentRole.SUPERVISOR,
                target_role,
                sub.get("goal", goal),
                max_risk=RiskTier.MUTATE if target_role == AgentRole.CODER else RiskTier.REMOTE,
                confirmed=True,  # supervisor executes confirmed workflow
            )
            collected_outputs.append(sub_res.output)
            if not sub_res.success:
                return sub_res

        # Step 3: Verification
        ver_res = self.delegate(
            AgentRole.SUPERVISOR,
            AgentRole.VERIFIER,
            f"Verify all {len(subtasks)} steps completed for '{goal}'",
            max_risk=RiskTier.READ,
        )
        collected_outputs.append(ver_res.output)

        if not ver_res.success:
            return AgentResult(
                success=False,
                output=f"Task orchestration completed with verification issues: {ver_res.output}",
                role=AgentRole.SUPERVISOR,
            )

        summary = "\n".join(collected_outputs)
        return AgentResult(
            success=True,
            output=f"Supervisor orchestration succeeded for '{goal}':\n{summary}",
            data={"subtask_count": len(subtasks), "verified": True},
            role=AgentRole.SUPERVISOR,
        )

    def resolve_conflicts(self, results: list[AgentResult]) -> AgentResult:
        """Arbitrates between conflicting agent results."""
        has_failure = any(not r.success for r in results)
        if has_failure:
            failed_agents = [r.role.value for r in results if not r.success]
            return AgentResult(
                success=False,
                output=f"Supervisor arbitration: Rejected due to failures in agents: {', '.join(failed_agents)}",
                error="agent_conflict_detected",
                role=AgentRole.SUPERVISOR,
            )
        return AgentResult(
            success=True,
            output="Supervisor arbitration: All agent outcomes unanimous and approved",
            role=AgentRole.SUPERVISOR,
        )
