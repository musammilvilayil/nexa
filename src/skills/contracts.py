from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from core.contracts import (
    ExecutionResult,
    OperationSpec,
    RiskTier,
    Skill,
    SkillMatch,
    SkillMetadata,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ParameterDefinition:
    """Defines a parameter expected by a skill operation."""
    name: str
    type_name: str = "str"
    required: bool = True
    default: Any = None
    description: str = ""


@dataclass(frozen=True)
class EnhancedOperationSpec(OperationSpec):
    """Enhanced operation specification including parameters and recovery strategies."""
    parameters: tuple[ParameterDefinition, ...] = ()
    recovery_strategies: tuple[str, ...] = ()
    idempotent: bool = False


class BaseSkill(ABC):
    """Universal foundational skill base class for all NEXA capability skills.
    
    Fulfills core.contracts.Skill while adding:
    1. Schema-based parameter validation
    2. Post-execution state verification (`verify`)
    3. Automated recovery on failure (`recover`)
    4. Deterministic self-testing (`run_self_tests`)
    """

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        operations: Sequence[OperationSpec | EnhancedOperationSpec] = (),
        required_resources: Sequence[str] = (),
    ) -> None:
        self._name = name
        self._version = version
        self._description = description
        self._operations = tuple(operations)
        self._required_resources = tuple(required_resources)
        self._metadata = SkillMetadata(
            name=name,
            version=version,
            description=description,
            operations=self._operations,
            required_resources=self._required_resources,
        )

    @property
    def metadata(self) -> SkillMetadata:
        return self._metadata

    @property
    def name(self) -> str:
        return self._name

    @abstractmethod
    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        """Evaluate whether this skill can handle the given text."""
        raise NotImplementedError

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Validate input parameters for the given operation against its spec."""
        op_spec = self.metadata.operation(operation)
        if op_spec is None:
            raise ValueError(f"Skill '{self._name}' has no operation '{operation}'")

        cleaned = dict(params)
        if isinstance(op_spec, EnhancedOperationSpec):
            for p_def in op_spec.parameters:
                if p_def.required and p_def.name not in cleaned:
                    if p_def.default is not None:
                        cleaned[p_def.name] = p_def.default
                    else:
                        raise ValueError(
                            f"Operation '{operation}' requires parameter '{p_def.name}'"
                        )
        return cleaned

    @abstractmethod
    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        """Execute the requested operation."""
        raise NotImplementedError

    def verify(
        self,
        operation: str,
        params: Mapping[str, Any],
        result: Any,
        context: Mapping[str, Any] | None = None,
    ) -> bool:
        """Verify that the operation produced the intended real-world effect."""
        if hasattr(result, "success"):
            return bool(result.success)
        return True

    def recover(
        self,
        operation: str,
        params: Mapping[str, Any],
        error: str,
        context: Mapping[str, Any] | None = None,
    ) -> ExecutionResult | None:
        """Attempt automated recovery from an execution failure."""
        logger.warning(
            "Default recovery invoked for %s.%s with error: %s",
            self._name,
            operation,
            error,
        )
        return None

    def run_self_tests(self) -> dict[str, bool]:
        """Run self-contained deterministic diagnostic tests for this skill."""
        results: dict[str, bool] = {}
        results[f"{self._name}_metadata_valid"] = bool(
            self.metadata.name and len(self.metadata.operations) > 0
        )
        return results
