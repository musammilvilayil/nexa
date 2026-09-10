from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

class PlanStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIALLY_COMPLETED = "partially_completed"
    ROLLED_BACK = "rolled_back"

class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ROLLED_BACK = "rolled_back"

@dataclass
class PlanStep:
    """A single step in a task plan."""
    step_id: int
    description: str
    skill_name: str
    operation: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: tuple[int, ...] = ()
    verify_condition: str = ""  # Human-readable verification condition
    rollback_operation: str = ""  # Operation to undo this step
    rollback_params: dict[str, Any] = field(default_factory=dict)
    status: StepStatus = StepStatus.PENDING
    result: Any = None
    error: str | None = None
    retry_count: int = 0
    max_retries: int = 1

@dataclass
class TaskPlan:
    """A multi-step execution plan."""
    plan_id: str
    description: str
    steps: list[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.PENDING
    original_request: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: str | None = None

@dataclass(frozen=True)
class PlanResult:
    """Result of executing a task plan."""
    plan: TaskPlan
    success: bool
    message: str
    completed_steps: int = 0
    total_steps: int = 0
    errors: tuple[str, ...] = ()
