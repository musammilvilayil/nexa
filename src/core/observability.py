from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from core.contracts import RiskTier


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ActivityEvent:
    event_id: str
    category: str  # task, plan, tool, security, mcp, agent, memory
    action: str
    details: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0
    status: str = "success"  # success, failed, denied, pending
    timestamp: str = field(default_factory=_utc_now)


@dataclass
class SecurityDecisionLog:
    timestamp: str
    skill_name: str
    operation: str
    risk_tier: str
    outcome: str
    reason: str
    confirmed: bool


@dataclass
class MetricSummary:
    count: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float("inf")
    max_latency_ms: float = 0.0
    error_count: int = 0

    def record(self, latency_ms: float, success: bool = True) -> None:
        self.count += 1
        self.total_latency_ms += latency_ms
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)
        if not success:
            self.error_count += 1

    @property
    def avg_latency_ms(self) -> float:
        return (self.total_latency_ms / self.count) if self.count > 0 else 0.0


class ObservabilityEngine:
    """Central observability system tracking real-time activity, metrics, security audits, and decision explainability."""

    def __init__(self, max_events: int = 1000) -> None:
        self.max_events = max_events
        self._activities: list[ActivityEvent] = []
        self._security_decisions: list[SecurityDecisionLog] = []
        self._metrics: dict[str, MetricSummary] = {}
        self._explanations: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def log_activity(
        self,
        category: str,
        action: str,
        details: Mapping[str, Any] | None = None,
        duration_ms: float = 0.0,
        status: str = "success",
    ) -> ActivityEvent:
        with self._lock:
            event = ActivityEvent(
                event_id=f"act_{len(self._activities) + 1}",
                category=category,
                action=action,
                details=dict(details or {}),
                duration_ms=duration_ms,
                status=status,
            )
            self._activities.append(event)
            if len(self._activities) > self.max_events:
                self._activities.pop(0)

            # Record metric automatically
            metric_key = f"{category}.{action}"
            if metric_key not in self._metrics:
                self._metrics[metric_key] = MetricSummary()
            self._metrics[metric_key].record(duration_ms, success=(status == "success"))

            return event

    def log_security_decision(
        self,
        skill_name: str,
        operation: str,
        risk: RiskTier,
        outcome: str,
        reason: str = "",
        confirmed: bool = False,
    ) -> SecurityDecisionLog:
        with self._lock:
            log = SecurityDecisionLog(
                timestamp=_utc_now(),
                skill_name=skill_name,
                operation=operation,
                risk_tier=risk.value,
                outcome=outcome,
                reason=reason,
                confirmed=confirmed,
            )
            self._security_decisions.append(log)
            if len(self._security_decisions) > self.max_events:
                self._security_decisions.pop(0)
            return log

    def record_decision_rationale(
        self,
        identifier: str,
        goal: str,
        chosen_path: str,
        considered_options: list[str],
        reasoning: str,
        policy_checks: list[dict[str, Any]] | None = None,
    ) -> None:
        with self._lock:
            self._explanations[identifier] = {
                "identifier": identifier,
                "goal": goal,
                "chosen_path": chosen_path,
                "considered_options": list(considered_options),
                "reasoning": reasoning,
                "policy_checks": list(policy_checks or []),
                "recorded_at": _utc_now(),
            }

    def explain_decision(self, identifier: str) -> dict[str, Any]:
        with self._lock:
            if identifier in self._explanations:
                return dict(self._explanations[identifier])
            # Fallback heuristic explanation
            return {
                "identifier": identifier,
                "explanation": f"Decision for '{identifier}' followed deterministic skill matching and security tier policy.",
                "status": "inferred",
            }

    def get_recent_activity(
        self,
        limit: int = 50,
        category: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            events = self._activities
            if category:
                events = [e for e in events if e.category == category]
            selected = events[-limit:] if limit > 0 else events
            return [asdict(e) for e in selected]

    def get_security_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            selected = self._security_decisions[-limit:] if limit > 0 else self._security_decisions
            return [asdict(s) for s in selected]

    def get_metrics_summary(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return {
                name: {
                    "count": m.count,
                    "avg_latency_ms": round(m.avg_latency_ms, 2),
                    "min_latency_ms": 0.0 if m.min_latency_ms == float("inf") else round(m.min_latency_ms, 2),
                    "max_latency_ms": round(m.max_latency_ms, 2),
                    "error_count": m.error_count,
                }
                for name, m in self._metrics.items()
            }

    def health_summary(self) -> dict[str, Any]:
        with self._lock:
            total_ops = sum(m.count for m in self._metrics.values())
            total_errors = sum(m.error_count for m in self._metrics.values())
            success_rate = (1.0 - (total_errors / total_ops)) if total_ops > 0 else 1.0
            return {
                "healthy": total_errors == 0 or success_rate >= 0.95,
                "total_activities": len(self._activities),
                "total_security_checks": len(self._security_decisions),
                "tracked_operations": len(self._metrics),
                "success_rate": round(success_rate * 100.0, 1),
            }
