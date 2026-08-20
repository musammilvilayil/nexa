from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from core import KernelResponse


@dataclass(frozen=True)
class RuntimeHealthSnapshot:
    ok: bool
    state: str
    checked_at_utc: datetime
    details: dict[str, Any]
    errors: tuple[str, ...] = ()


class RuntimeControlPlane:
    """Shared local control boundary for CLI, API, and future voice adapters.

    All natural-language/action requests still enter through ``NexaKernel``.
    This class exposes lifecycle/status helpers, but it does not provide a direct
    live-order method or any path around skill validation, confirmation, audit,
    RiskEngine, strategy promotion, live arming, or the trading kill switch.
    """

    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime
        self._stopped = False
        self._started_at_utc = datetime.now(timezone.utc)

    @property
    def stopped(self) -> bool:
        return self._stopped

    def process(self, text: str) -> KernelResponse:
        if self._stopped:
            raise RuntimeError("NEXA runtime control plane is stopped")
        command = text.strip()
        if not command:
            raise ValueError("command required")
        return self.runtime.kernel.process(command)

    def confirm(self, action_id: str) -> KernelResponse:
        if self._stopped:
            raise RuntimeError("NEXA runtime control plane is stopped")
        key = action_id.strip()
        if not key:
            raise ValueError("action_id required")
        return self.runtime.kernel.confirm(key)

    def cancel(self, action_id: str) -> KernelResponse:
        if self._stopped:
            raise RuntimeError("NEXA runtime control plane is stopped")
        key = action_id.strip()
        if not key:
            raise ValueError("action_id required")
        return self.runtime.kernel.cancel(key)

    def status(self) -> dict[str, Any]:
        brain = self.runtime.trading_brain
        portfolio = brain.paper_broker.portfolio
        evidence_payload: dict[str, Any] | None = None
        evidence = brain.paper_evidence()
        if evidence is not None:
            evidence_payload = {
                "session_id": evidence.session_id,
                "started_at_utc": evidence.started_at_utc.isoformat(),
                "consistent": evidence.consistent,
                "reasons": list(evidence.reasons),
                "trading_days": evidence.evidence.trading_days,
                "closed_trades": evidence.evidence.closed_trades,
                "net_pnl": evidence.evidence.net_pnl,
                "max_drawdown_pct": evidence.evidence.max_drawdown_pct,
                "safety_violations": evidence.evidence.safety_violations,
            }

        return {
            "state": "stopped" if self._stopped else "ready",
            "started_at_utc": self._started_at_utc.isoformat(),
            "skills": [item.name for item in self.runtime.registry.list_metadata()],
            "trading": {
                "mode": brain.mandate.mode.value,
                "strategy_id": brain.strategy.strategy_id,
                "strategy_stage": brain.stage.value,
                "paper_runtime_armed": brain.paper_runtime_armed,
                "paper_positions": len(portfolio.positions),
                "paper_orders": len(brain.paper_broker.orders),
                "paper_realized_pnl_total": portfolio.realized_pnl_total,
                "paper_evidence": evidence_payload,
                "live_broker_configured": self.runtime.live_controller is not None,
                "live_armed": self.runtime.live_arm.is_armed_for(brain.mandate),
                "kill_switch_active": self.runtime.kill_switch.active,
                "kill_switch_reason": self.runtime.kill_switch.reason,
            },
        }

    def health(self) -> RuntimeHealthSnapshot:
        errors: list[str] = []
        details: dict[str, Any] = {}

        try:
            restored = self.runtime.paper_state_store.load()
            details["paper_state"] = {
                "positions": len(restored.portfolio.positions),
                "orders": len(restored.orders),
                "protective_signals": len(restored.protective_signals),
                "last_processed_symbols": len(restored.last_processed),
            }
        except Exception as exc:
            errors.append(f"paper state recovery failed: {type(exc).__name__}: {exc}")

        try:
            evidence = self.runtime.paper_evidence_store.report()
            details["paper_evidence"] = {
                "session_id": evidence.session_id,
                "consistent": evidence.consistent,
                "safety_violations": evidence.evidence.safety_violations,
            }
            if not evidence.consistent:
                errors.append("paper evidence ledger is inconsistent")
        except Exception as exc:
            errors.append(f"paper evidence recovery failed: {type(exc).__name__}: {exc}")

        try:
            details["strategy_stage"] = self.runtime.trading_brain.stage.value
        except Exception as exc:
            errors.append(f"strategy promotion state unavailable: {type(exc).__name__}: {exc}")

        details["live_broker_configured"] = self.runtime.live_controller is not None
        details["live_armed"] = self.runtime.live_arm.is_armed_for(self.runtime.trading_brain.mandate)
        details["kill_switch_active"] = self.runtime.kill_switch.active

        return RuntimeHealthSnapshot(
            ok=not errors and not self._stopped,
            state="stopped" if self._stopped else ("ready" if not errors else "degraded"),
            checked_at_utc=datetime.now(timezone.utc),
            details=details,
            errors=tuple(errors),
        )

    def shutdown(self) -> None:
        """Fail closed for new autonomous work while preserving persisted state."""

        if self._stopped:
            return
        self.runtime.trading_brain.disarm_paper_runtime()
        self.runtime.live_arm.disarm()
        self._stopped = True


def kernel_response_payload(response: KernelResponse) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": response.status,
        "message": response.message,
    }
    if response.result is not None:
        payload["result"] = {
            "success": response.result.success,
            "message": response.result.message,
            "data": response.result.data,
            "error": response.result.error,
        }
    if response.pending_action is not None:
        action = response.pending_action
        payload["pending_action"] = {
            "action_id": action.action_id,
            "skill": action.skill_name,
            "operation": action.operation,
            "params": dict(action.params),
            "risk": action.risk.value,
            "created_at_utc": action.created_at_utc.isoformat(),
            "expires_at_utc": action.expires_at_utc.isoformat(),
        }
    return payload


def health_payload(snapshot: RuntimeHealthSnapshot) -> dict[str, Any]:
    return {
        "ok": snapshot.ok,
        "state": snapshot.state,
        "checked_at_utc": snapshot.checked_at_utc.isoformat(),
        "details": snapshot.details,
        "errors": list(snapshot.errors),
    }
