from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable

from planner.contracts import (
    TaskPlan,
    PlanStep,
    PlanResult,
    PlanStatus,
    StepStatus,
    TaskRecord,
)
from planner.task_store import TaskStore


class PlanExecutor:
    """Executes task plans step by step with verification, recovery, and persistence.
    
    For each step:
    1. Check if task was cancelled
    2. Check dependencies are met
    3. Execute via kernel
    4. Verify success
    5. On failure: bounded retry with backoff, then attempt rollback
    6. Persist state to TaskStore
    """

    def __init__(
        self,
        kernel_process: Callable[[str], Any] | None = None,
        task_store: TaskStore | None = None,
    ) -> None:
        self._kernel_process = kernel_process
        self._task_store = task_store

    def execute(self, plan: TaskPlan) -> PlanResult:
        """Execute all steps in order, respecting dependencies."""
        now = datetime.now(timezone.utc).isoformat()
        if plan.status != PlanStatus.CANCELLED:
            plan.status = PlanStatus.IN_PROGRESS

        task_record = TaskRecord(
            task_id=plan.plan_id,
            goal=plan.description,
            plan=plan,
            current_step=0,
            state="in_progress",
            started_at=now,
            updated_at=now,
        )
        if self._task_store is not None:
            self._task_store.save_task(task_record)

        errors: list[str] = []
        completed = 0
        total_recoveries = 0

        for idx, step in enumerate(plan.steps, 1):
            task_record.current_step = idx
            
            # Check for cancellation
            if plan.status == PlanStatus.CANCELLED:
                step.status = StepStatus.SKIPPED
                continue

            if not self._check_dependencies(step, plan):
                step.status = StepStatus.SKIPPED
                continue

            success = self._execute_step(step, plan)
            if success:
                completed += 1
                task_record.verification_result = f"Step {idx} verified"
            else:
                errors.append(step.error or "Unknown error")
                task_record.failure_reason = step.error
                task_record.verification_result = f"Step {idx} failed verification"
                self._rollback(plan, step.step_id)
                continue

            total_recoveries += step.retry_count
            task_record.recovery_count = total_recoveries
            task_record.updated_at = datetime.now(timezone.utc).isoformat()
            if self._task_store is not None:
                self._task_store.save_task(task_record)

        now_end = datetime.now(timezone.utc).isoformat()
        plan.completed_at = now_end

        if plan.status == PlanStatus.CANCELLED:
            success = False
            task_record.state = "cancelled"
            msg = "Plan was cancelled by user"
        elif len(plan.steps) == 0 or completed == len(plan.steps):
            plan.status = PlanStatus.COMPLETED
            success = True
            task_record.state = "completed"
            msg = "Plan execution finished successfully"
        elif completed > 0:
            plan.status = PlanStatus.PARTIALLY_COMPLETED
            success = False
            task_record.state = "partially_completed"
            msg = f"Plan partially completed: {'; '.join(errors)}"
        else:
            plan.status = PlanStatus.FAILED
            success = False
            task_record.state = "failed"
            msg = f"Plan failed: {'; '.join(errors)}"

        task_record.updated_at = now_end
        if self._task_store is not None:
            self._task_store.save_task(task_record)

        return PlanResult(
            plan=plan,
            success=success,
            message=msg,
            completed_steps=completed,
            total_steps=len(plan.steps),
            errors=tuple(errors),
        )

    def _execute_step(self, step: PlanStep, plan: TaskPlan) -> bool:
        """Execute a single step with bounded retries and backoff."""
        step.status = StepStatus.IN_PROGRESS

        while step.retry_count <= step.max_retries:
            try:
                if self._kernel_process:
                    cmd = step.description
                    result = self._kernel_process(cmd)
                    if result == "FAIL":
                        raise RuntimeError("Kernel execution returned failure status")
                    if hasattr(result, "status"):
                        if result.status not in ("success", "ok"):
                            err_msg = getattr(result, "message", "Execution failed")
                            raise RuntimeError(err_msg)
                    step.result = result
                else:
                    step.result = "Success"

                step.status = StepStatus.COMPLETED
                return True
            except Exception as e:
                step.error = str(e)
                if step.retry_count < step.max_retries:
                    step.retry_count += 1
                    # Bounded exponential backoff
                    time.sleep(0.05 * (2 ** step.retry_count))
                else:
                    break

        step.status = StepStatus.FAILED
        return False

    def _check_dependencies(self, step: PlanStep, plan: TaskPlan) -> bool:
        """Check if all dependency steps are completed."""
        for dep_id in step.depends_on:
            for p_step in plan.steps:
                if p_step.step_id == dep_id and p_step.status != StepStatus.COMPLETED:
                    return False
        return True

    def _rollback(self, plan: TaskPlan, failed_step_id: int) -> None:
        """Rollback completed steps in reverse order if compensation is defined."""
        plan.status = PlanStatus.ROLLED_BACK
        for step in reversed(plan.steps):
            if step.status == StepStatus.COMPLETED:
                if step.rollback_operation and self._kernel_process:
                    try:
                        self._kernel_process(step.rollback_operation)
                    except Exception:
                        pass
                step.status = StepStatus.ROLLED_BACK
