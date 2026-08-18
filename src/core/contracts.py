from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Protocol


class RiskTier(str, Enum):
    READ = "read"
    MUTATE = "mutate"
    REMOTE = "remote"
    DESTRUCTIVE = "destructive"


class PolicyOutcome(str, Enum):
    ALLOW = "allow"
    REQUIRE_CONFIRMATION = "require_confirmation"
    DENY = "deny"


@dataclass(frozen=True)
class OperationSpec:
    name: str
    description: str
    risk: RiskTier


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    version: str
    description: str
    operations: tuple[OperationSpec, ...]
    required_resources: tuple[str, ...] = ()

    def operation(self, name: str) -> OperationSpec | None:
        for operation in self.operations:
            if operation.name == name:
                return operation
        return None


@dataclass(frozen=True)
class SkillMatch:
    skill_name: str
    operation: str
    params: Mapping[str, Any] = field(default_factory=dict)
    confidence: float = 1.0


@dataclass(frozen=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reason: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    message: str
    data: Any = None
    error: str | None = None


class Skill(Protocol):
    @property
    def metadata(self) -> SkillMetadata:
        ...

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        ...

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        ...

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        ...
