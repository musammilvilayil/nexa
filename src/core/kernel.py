from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from .context import ContextBus, ContextSnapshot
from .contracts import ExecutionResult, PolicyOutcome
from .dispatcher import Dispatcher
from .registry import SkillRegistry
from .security import SecurityGate


@dataclass(frozen=True)
class PendingAction:
    action_id: str
    skill_name: str
    operation: str
    params: Mapping[str, Any]
    context: ContextSnapshot


@dataclass(frozen=True)
class KernelResponse:
    status: str
    message: str
    result: ExecutionResult | None = None
    pending_action: PendingAction | None = None


class NexaKernel:
    """Standalone orchestration engine for NEXA.

    The kernel resolves registered skills, validates arguments, applies generic
    risk policy, dispatches execution, and preserves exact pending actions for
    later confirmation. It contains no capability-specific logic.
    """

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        context_bus: ContextBus | None = None,
        security_gate: SecurityGate | None = None,
        dispatcher: Dispatcher | None = None,
    ) -> None:
        self.registry = registry or SkillRegistry()
        self.context_bus = context_bus or ContextBus()
        self.security_gate = security_gate or SecurityGate()
        self.dispatcher = dispatcher or Dispatcher()
        self._pending: dict[str, PendingAction] = {}

    def process(self, text: str) -> KernelResponse:
        snapshot = self.context_bus.snapshot()
        context = snapshot.as_mapping()
        match = self.registry.resolve(text, context)

        if match is None:
            return KernelResponse(
                status="no_match",
                message="No registered skill matched the request.",
            )

        skill = self.registry.get(match.skill_name)
        spec = skill.metadata.operation(match.operation)
        if spec is None:
            return KernelResponse(
                status="error",
                message=f"Skill operation is not registered: {match.operation}",
            )

        try:
            validated = self.dispatcher.validate(
                skill,
                match.operation,
                match.params,
                context,
            )
        except Exception as exc:
            return KernelResponse(status="error", message=f"Validation failed: {exc}")

        decision = self.security_gate.decide(spec.risk)

        if decision.outcome == PolicyOutcome.DENY:
            return KernelResponse(status="denied", message=decision.reason)

        if decision.outcome == PolicyOutcome.REQUIRE_CONFIRMATION:
            action = PendingAction(
                action_id=uuid4().hex[:12],
                skill_name=skill.metadata.name,
                operation=match.operation,
                params=dict(validated),
                context=snapshot,
            )
            self._pending[action.action_id] = action
            return KernelResponse(
                status="confirmation_required",
                message=decision.reason,
                pending_action=action,
            )

        return self._execute(
            skill_name=skill.metadata.name,
            operation=match.operation,
            params=validated,
            snapshot=snapshot,
            confirmed=False,
        )

    def confirm(self, action_id: str) -> KernelResponse:
        action = self._pending.pop(action_id, None)
        if action is None:
            return KernelResponse(status="error", message="Pending action not found.")

        skill = self.registry.get(action.skill_name)
        spec = skill.metadata.operation(action.operation)
        if spec is None:
            return KernelResponse(status="error", message="Pending operation is no longer registered.")

        decision = self.security_gate.decide(spec.risk, confirmed=True)
        if decision.outcome != PolicyOutcome.ALLOW:
            return KernelResponse(status="denied", message=decision.reason)

        # Important: confirmation executes the exact validated request that was
        # stored earlier. User/model text is not parsed a second time.
        return self._execute(
            skill_name=action.skill_name,
            operation=action.operation,
            params=action.params,
            snapshot=action.context,
            confirmed=True,
        )

    def pending_actions(self) -> tuple[PendingAction, ...]:
        return tuple(self._pending.values())

    def _execute(
        self,
        *,
        skill_name: str,
        operation: str,
        params: Mapping[str, Any],
        snapshot: ContextSnapshot,
        confirmed: bool,
    ) -> KernelResponse:
        skill = self.registry.get(skill_name)
        try:
            result = self.dispatcher.execute(
                skill,
                operation,
                params,
                snapshot.as_mapping(),
            )
        except Exception as exc:
            return KernelResponse(status="error", message=f"Execution failed: {exc}")

        status = "success" if result.success else "failure"
        return KernelResponse(status=status, message=result.message, result=result)
