from __future__ import annotations

from typing import Any, Mapping

from .contracts import ExecutionResult, Skill


class DispatchError(RuntimeError):
    pass


class Dispatcher:
    """Validates and executes one already-resolved skill operation."""

    def validate(
        self,
        skill: Skill,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        spec = skill.metadata.operation(operation)
        if spec is None:
            raise DispatchError(
                f"Skill {skill.metadata.name} does not expose operation {operation}"
            )
        validated = skill.validate(operation, params, context)
        if not isinstance(validated, Mapping):
            raise DispatchError("Skill validator must return a mapping")
        return dict(validated)

    def execute(
        self,
        skill: Skill,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        result = skill.execute(operation, params, context)
        if not isinstance(result, ExecutionResult):
            raise DispatchError("Skill executor must return ExecutionResult")
        return result
