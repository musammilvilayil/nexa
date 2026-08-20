from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class TrainingDomain(str, Enum):
    LANGUAGE = "language"
    GENERAL_SKILL = "general_skill"
    TRADING_RESEARCH = "trading_research"
    TRADING_STRATEGY = "trading_strategy"


class CandidateRisk(str, Enum):
    READ_ONLY = "read_only"
    LOCAL_MUTATION = "local_mutation"
    REMOTE = "remote"
    DESTRUCTIVE = "destructive"
    LIVE_TRADING = "live_trading"


@dataclass(frozen=True)
class TrainingPolicy:
    max_attempts: int = 3
    max_teacher_calls: int = 6
    auto_promote_read_only: bool = True
    auto_promote_paper_trading: bool = True
    require_human_for_live_trading: bool = True
    require_human_for_remote_or_destructive: bool = True

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if self.max_teacher_calls < 1:
            raise ValueError("max_teacher_calls must be at least 1")


@dataclass(frozen=True)
class TrainingNeed:
    need_id: str
    domain: TrainingDomain
    objective: str
    context: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.need_id.strip():
            raise ValueError("need_id cannot be empty")
        if not self.objective.strip():
            raise ValueError("objective cannot be empty")


@dataclass(frozen=True)
class SkillCandidate:
    name: str
    description: str
    risk: CandidateRisk
    files: Mapping[str, str]
    intents: tuple[str, ...] = ()
    teacher_notes: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("candidate name cannot be empty")
        if not self.files:
            raise ValueError("candidate files cannot be empty")
        if "skill.py" not in self.files:
            raise ValueError("candidate must include skill.py")
        if not any(name.startswith("test_") and name.endswith(".py") for name in self.files):
            raise ValueError("candidate must include at least one test_*.py file")


@dataclass(frozen=True)
class TrainingAttempt:
    number: int
    sandbox_passed: bool
    reason: str
    teacher_calls_used: int


@dataclass(frozen=True)
class TrainingReport:
    need: TrainingNeed
    success: bool
    candidate: SkillCandidate | None
    attempts: tuple[TrainingAttempt, ...]
    promotion_status: str
    reason: str
