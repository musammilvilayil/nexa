from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from .audit import AuditLedger, AuditStatus
from .context import ContextBus, ContextSnapshot
from .contracts import ExecutionResult, PolicyOutcome, RiskTier
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
    action_id: str | None = None


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
        audit_ledger: AuditLedger | None = None,
    ) -> None:
        self.registry = registry or SkillRegistry()
        self.context_bus = context_bus or ContextBus()
        self.security_gate = security_gate or SecurityGate()
        self.dispatcher = dispatcher or Dispatcher()
        self.audit_ledger = audit_ledger
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

        action_id = uuid4().hex[:12]
        try:
            validated = self.dispatcher.validate(
                skill,
                match.operation,
                match.params,
                context,
            )
        except Exception as exc:
            audit_error = self._record_safely(
                action_id=action_id,
                skill_name=skill.metadata.name,
                operation=match.operation,
                params=match.params,
                risk=spec.risk,
                status=AuditStatus.VALIDATION_FAILED,
                error=str(exc),
            )
            suffix = f"; audit failed: {audit_error}" if audit_error else ""
            return KernelResponse(
                status="error",
                message=f"Validation failed: {exc}{suffix}",
                action_id=action_id,
            )

        decision = self.security_gate.decide(spec.risk)

        if decision.outcome == PolicyOutcome.DENY:
            audit_error = self._record_safely(
                action_id=action_id,
                skill_name=skill.metadata.name,
                operation=match.operation,
                params=validated,
                risk=spec.risk,
                status=AuditStatus.DENIED,
                error=decision.reason,
            )
            suffix = f"; audit failed: {audit_error}" if audit_error else ""
            return KernelResponse(
                status="denied",
                message=f"{decision.reason}{suffix}",
                action_id=action_id,
            )

        if decision.outcome == PolicyOutcome.REQUIRE_CONFIRMATION:
            action = PendingAction(
                action_id=action_id,
                skill_name=skill.metadata.name,
                operation=match.operation,
                params=dict(validated),
                context=snapshot,
            )
            audit_error = self._record_safely(
                action_id=action_id,
                skill_name=skill.metadata.name,
                operation=match.operation,
                params=validated,
                risk=spec.risk,
                status=AuditStatus.PENDING,
            )
            if audit_error:
                return KernelResponse(
                    status="error",
                    message=f"Pending action was not armed because audit failed: {audit_error}",
                    action_id=action_id,
                )
            self._pending[action.action_id] = action
            return KernelResponse(
                status="confirmation_required",
                message=decision.reason,
                pending_action=action,
                action_id=action_id,
            )

        return self._execute(
            action_id=action_id,
            skill_name=skill.metadata.name,
            operation=match.operation,
            params=validated,
            snapshot=snapshot,
            risk=spec.risk,
            confirmed=False,
        )

    def confirm(self, action_id: str) -> KernelResponse:
        action = self._pending.pop(action_id, None)
        if action is None:
            return KernelResponse(status="error", message="Pending action not found.")

        skill = self.registry.get(action.skill_name)
        spec = skill.metadata.operation(action.operation)
        if spec is None:
            return KernelResponse(
                status="error",
                message="Pending operation is no longer registered.",
                action_id=action_id,
            )

        decision = self.security_gate.decide(spec.risk, confirmed=True)
        if decision.outcome != PolicyOutcome.ALLOW:
            audit_error = self._record_safely(
                action_id=action.action_id,
                skill_name=action.skill_name,
                operation=action.operation,
                params=action.params,
                risk=spec.risk,
                status=AuditStatus.DENIED,
                confirmed=True,
                error=decision.reason,
            )
            suffix = f"; audit failed: {audit_error}" if audit_error else ""
            return KernelResponse(
                status="denied",
                message=f"{decision.reason}{suffix}",
                action_id=action_id,
            )

        # Confirmation executes the exact validated request stored earlier.
        # User/model text is never parsed a second time.
        return self._execute(
            action_id=action.action_id,
            skill_name=action.skill_name,
            operation=action.operation,
            params=action.params,
            snapshot=action.context,
            risk=spec.risk,
            confirmed=True,
        )

    def pending_actions(self) -> tuple[PendingAction, ...]:
        return tuple(self._pending.values())

    def _execute(
        self,
        *,
        action_id: str,
        skill_name: str,
        operation: str,
        params: Mapping[str, Any],
        snapshot: ContextSnapshot,
        risk: RiskTier,
        confirmed: bool,
    ) -> KernelResponse:
        audit_error = self._record_safely(
            action_id=action_id,
            skill_name=skill_name,
            operation=operation,
            params=params,
            risk=risk,
            status=AuditStatus.STARTED,
            confirmed=confirmed,
        )
        if audit_error:
            return KernelResponse(
                status="error",
                message=f"Execution blocked because audit could not start: {audit_error}",
                action_id=action_id,
            )

        skill = self.registry.get(skill_name)
        try:
            result = self.dispatcher.execute(
                skill,
                operation,
                params,
                snapshot.as_mapping(),
            )
        except Exception as exc:
            final_audit_error = self._record_safely(
                action_id=action_id,
                skill_name=skill_name,
                operation=operation,
                params=params,
                risk=risk,
                status=AuditStatus.FAILURE,
                confirmed=confirmed,
                error=str(exc),
            )
            suffix = f"; final audit failed: {final_audit_error}" if final_audit_error else ""
            return KernelResponse(
                status="error",
                message=f"Execution failed: {exc}{suffix}",
                action_id=action_id,
            )

        final_status = AuditStatus.SUCCESS if result.success else AuditStatus.FAILURE
        final_audit_error = self._record_safely(
            action_id=action_id,
            skill_name=skill_name,
            operation=operation,
            params=params,
            risk=risk,
            status=final_status,
            confirmed=confirmed,
            result={
                "success": result.success,
                "message": result.message,
                "data": result.data,
                "error": result.error,
            },
            error=result.error,
        )
        if final_audit_error:
            return KernelResponse(
                status="audit_error",
                message=f"Action executed but final audit update failed: {final_audit_error}",
                result=result,
                action_id=action_id,
            )

        status = "success" if result.success else "failure"
        return KernelResponse(
            status=status,
            message=result.message,
            result=result,
            action_id=action_id,
        )

    def _record_safely(
        self,
        *,
        action_id: str,
        skill_name: str,
        operation: str,
        params: Mapping[str, Any],
        risk: RiskTier,
        status: AuditStatus,
        confirmed: bool = False,
        result: Any = None,
        error: str | None = None,
    ) -> str | None:
        if self.audit_ledger is None:
            return None
        try:
            self.audit_ledger.record(
                action_id=action_id,
                skill_name=skill_name,
                operation=operation,
                params=params,
                risk_tier=risk.value,
                status=status,
                confirmed=confirmed,
                result=result,
                error=error,
            )
            return None
        except Exception as exc:
            return str(exc)
