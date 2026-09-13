from __future__ import annotations

import heapq
import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable
from uuid import uuid4

from planner.contracts import (
    PlanResult,
    PlanStatus,
    PlanStep,
    StepStatus,
    TaskPlan,
    TaskRecord,
)
from planner.executor import PlanExecutor
from planner.task_store import TaskStore


class TaskPriority(int, Enum):
    CRITICAL = 100
    HIGH = 75
    NORMAL = 50
    LOW = 25


class LongRunningTaskState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class TaskProgress:
    task_id: str
    current_step: int
    total_steps: int
    percent: float
    elapsed_seconds: float
    eta_seconds: float | None
    state: LongRunningTaskState
    message: str


@dataclass
class LongRunningTask:
    task_id: str
    goal: str
    plan: TaskPlan
    priority: TaskPriority = TaskPriority.NORMAL
    state: LongRunningTaskState = LongRunningTaskState.PENDING
    current_step_idx: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    completed_at: float | None = None
    checkpoints: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def __lt__(self, other: LongRunningTask) -> bool:
        # Higher priority first; if equal, earlier created_at first
        if self.priority != other.priority:
            return self.priority.value > other.priority.value
        return self.created_at < other.created_at


class LongRunningTaskManager:
    """Orchestrates long-running, multi-step tasks with priority, pause/resume, and checkpoint recovery."""

    def __init__(
        self,
        executor: PlanExecutor,
        task_store: TaskStore | None = None,
    ) -> None:
        self.executor = executor
        self.task_store = task_store
        self._tasks: dict[str, LongRunningTask] = {}
        self._queue: list[LongRunningTask] = []
        self._lock = threading.Lock()

    def submit_task(
        self,
        goal: str,
        plan: TaskPlan,
        priority: TaskPriority = TaskPriority.NORMAL,
        task_id: str | None = None,
    ) -> LongRunningTask:
        with self._lock:
            tid = task_id or plan.plan_id or f"task_{uuid4().hex[:8]}"
            plan.plan_id = tid
            plan.description = goal

            task = LongRunningTask(
                task_id=tid,
                goal=goal,
                plan=plan,
                priority=priority,
                state=LongRunningTaskState.PENDING,
            )
            self._tasks[tid] = task
            heapq.heappush(self._queue, task)

            self._persist_checkpoint(task, "Task submitted")
            return task

    def get_task(self, task_id: str) -> LongRunningTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def list_tasks(self, state: LongRunningTaskState | None = None) -> list[LongRunningTask]:
        with self._lock:
            tasks = list(self._tasks.values())
            if state is not None:
                tasks = [t for t in tasks if t.state == state]
            return sorted(tasks, key=lambda t: t.priority.value, reverse=True)

    def pause_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.state in (LongRunningTaskState.PENDING, LongRunningTaskState.RUNNING):
                task.state = LongRunningTaskState.PAUSED
                task.updated_at = time.time()
                self._persist_checkpoint(task, "Task paused by user")
                return True
            return False

    def resume_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.state == LongRunningTaskState.PAUSED:
                task.state = LongRunningTaskState.PENDING
                task.updated_at = time.time()
                heapq.heappush(self._queue, task)
                self._persist_checkpoint(task, "Task resumed by user")
                return True
            return False

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.state not in (LongRunningTaskState.COMPLETED, LongRunningTaskState.CANCELLED):
                task.state = LongRunningTaskState.CANCELLED
                task.plan.status = PlanStatus.CANCELLED
                task.updated_at = time.time()
                self._persist_checkpoint(task, "Task cancelled by user")
                return True
            return False

    def get_progress(self, task_id: str) -> TaskProgress | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None

            total = len(task.plan.steps)
            current = task.current_step_idx
            pct = (current / total * 100.0) if total > 0 else 0.0

            now = time.time()
            elapsed = (now - task.started_at) if task.started_at else 0.0
            eta = None
            if current > 0 and total > current and elapsed > 0:
                avg_per_step = elapsed / current
                eta = avg_per_step * (total - current)

            return TaskProgress(
                task_id=task.task_id,
                current_step=current,
                total_steps=total,
                percent=round(pct, 1),
                elapsed_seconds=round(elapsed, 1),
                eta_seconds=round(eta, 1) if eta is not None else None,
                state=task.state,
                message=f"Step {current}/{total} ({pct:.0f}%)",
            )

    def step_task(self, task_id: str) -> bool:
        """Executes the next step for the task."""
        with self._lock:
            task = self._tasks.get(task_id)
            if not task or task.state in (
                LongRunningTaskState.PAUSED,
                LongRunningTaskState.CANCELLED,
                LongRunningTaskState.COMPLETED,
                LongRunningTaskState.FAILED,
            ):
                return False

            if task.started_at is None:
                task.started_at = time.time()
            task.state = LongRunningTaskState.RUNNING

            steps = task.plan.steps
            if task.current_step_idx >= len(steps):
                task.state = LongRunningTaskState.COMPLETED
                task.plan.status = PlanStatus.COMPLETED
                task.completed_at = time.time()
                self._persist_checkpoint(task, "All steps completed")
                return False

            step = steps[task.current_step_idx]

        # Execute single step outside lock
        if not self.executor._check_dependencies(step, task.plan):
            with self._lock:
                step.status = StepStatus.SKIPPED
                task.current_step_idx += 1
                return True

        success = self.executor._execute_step(step, task.plan)

        with self._lock:
            if success:
                task.current_step_idx += 1
                task.updated_at = time.time()
                if task.current_step_idx >= len(steps):
                    task.state = LongRunningTaskState.COMPLETED
                    task.plan.status = PlanStatus.COMPLETED
                    task.completed_at = time.time()
                    self._persist_checkpoint(task, "Completed final step")
                    return False
                else:
                    self._persist_checkpoint(task, f"Completed step {task.current_step_idx}")
                    return True
            else:
                task.state = LongRunningTaskState.FAILED
                task.plan.status = PlanStatus.FAILED
                task.error = step.error or f"Step {step.step_id} failed"
                self._persist_checkpoint(task, f"Failed at step {task.current_step_idx + 1}")
                return False

    def run_task_sync(self, task_id: str) -> PlanResult:
        """Runs steps iteratively until completion, failure, or pause."""
        while True:
            with self._lock:
                task = self._tasks.get(task_id)
                if not task or task.state in (
                    LongRunningTaskState.PAUSED,
                    LongRunningTaskState.CANCELLED,
                    LongRunningTaskState.COMPLETED,
                    LongRunningTaskState.FAILED,
                ):
                    break

            more = self.step_task(task_id)
            if not more:
                break

        with self._lock:
            task = self._tasks[task_id]
            is_success = task.state == LongRunningTaskState.COMPLETED
            msg = f"Task {task_id}: {task.state.value}"
            return PlanResult(
                plan=task.plan,
                success=is_success,
                message=msg,
                completed_steps=task.current_step_idx,
            )

    def recover_interrupted_tasks(self) -> list[LongRunningTask]:
        """Scans TaskStore for interrupted tasks, restores checkpoints, marks them PAUSED ready for resume."""
        if not self.task_store:
            return []

        active_records = self.task_store.list_active_tasks()
        recovered: list[LongRunningTask] = []

        with self._lock:
            for rec in active_records:
                if rec.state in ("in_progress", "running") and rec.task_id not in self._tasks:
                    task = LongRunningTask(
                        task_id=rec.task_id,
                        goal=rec.goal,
                        plan=rec.plan,
                        state=LongRunningTaskState.PAUSED,  # Safe pause on reboot
                        current_step_idx=rec.current_step,
                        error="Recovered after system reboot; task paused safely.",
                    )
                    self._tasks[rec.task_id] = task
                    recovered.append(task)
                    self._persist_checkpoint(task, "Recovered from reboot")

        return recovered

    def _persist_checkpoint(self, task: LongRunningTask, note: str) -> None:
        checkpoint_entry = {
            "timestamp": time.time(),
            "step_index": task.current_step_idx,
            "state": task.state.value,
            "note": note,
        }
        task.checkpoints.append(checkpoint_entry)

        if self.task_store is not None:
            now_str = datetime.now(timezone.utc).isoformat()
            record = TaskRecord(
                task_id=task.task_id,
                goal=task.goal,
                plan=task.plan,
                current_step=task.current_step_idx,
                state=task.state.value,
                started_at=datetime.fromtimestamp(task.started_at, tz=timezone.utc).isoformat() if task.started_at else now_str,
                updated_at=now_str,
                failure_reason=task.error,
                verification_result=note,
            )
            self.task_store.save_task(record)
