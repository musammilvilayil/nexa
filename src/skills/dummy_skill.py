from __future__ import annotations

from typing import Any, Mapping

from core import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata


class DummySkill:
    """Small production-shaped plugin used to prove the kernel runtime pipeline."""

    def __init__(self) -> None:
        self.metadata = SkillMetadata(
            name="dummy",
            version="0.1.0",
            description="Kernel runtime demonstration skill",
            operations=(
                OperationSpec("ping", "Return PONG", RiskTier.READ),
                OperationSpec("remember", "Return a validated local mutation demo", RiskTier.MUTATE),
                OperationSpec("publish", "Simulate a remote action requiring confirmation", RiskTier.REMOTE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = " ".join(text.strip().split())
        lowered = normalized.lower()

        if lowered == "system ping":
            return SkillMatch("dummy", "ping")
        if lowered.startswith("remember "):
            return SkillMatch("dummy", "remember", {"value": normalized.split(" ", 1)[1]})
        if lowered.startswith("publish "):
            return SkillMatch("dummy", "publish", {"target": normalized.split(" ", 1)[1]})
        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation == "ping":
            return {}
        if operation == "remember":
            value = str(params.get("value", "")).strip()
            if not value:
                raise ValueError("value required")
            return {"value": value}
        if operation == "publish":
            target = str(params.get("target", "")).strip()
            if not target:
                raise ValueError("target required")
            return {"target": target}
        raise ValueError("unknown operation")

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        if operation == "ping":
            return ExecutionResult(True, "PONG")
        if operation == "remember":
            return ExecutionResult(True, f"remembered:{params['value']}")
        if operation == "publish":
            return ExecutionResult(True, f"published:{params['target']}")
        return ExecutionResult(False, "unknown operation", error="unknown operation")
