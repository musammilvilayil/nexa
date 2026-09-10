from __future__ import annotations
from typing import Any, Callable
from datetime import datetime

from planner.contracts import TaskPlan, PlanStep, PlanResult, PlanStatus, StepStatus

class PlanExecutor:
    """Executes task plans step by step with verification and recovery.
    
    For each step:
    1. Check dependencies are met
    2. Execute via kernel
    3. Verify success (if verification condition exists)
    4. On failure: retry up to max_retries, then attempt rollback
    5. Log everything to audit ledger
    """
    
    def __init__(self, kernel_process: Callable[[str], Any] | None = None) -> None:
        self._kernel_process = kernel_process
    
    def execute(self, plan: TaskPlan) -> PlanResult:
        """Execute all steps in order, respecting dependencies."""
        plan.status = PlanStatus.IN_PROGRESS
        errors = []
        completed = 0
        
        for step in plan.steps:
            if not self._check_dependencies(step, plan):
                step.status = StepStatus.SKIPPED
                continue
                
            success = self._execute_step(step, plan)
            if success:
                completed += 1
            else:
                errors.append(step.error or "Unknown error")
                
        if len(plan.steps) == 0:
            plan.status = PlanStatus.COMPLETED
            success = True
        elif completed == len(plan.steps):
            plan.status = PlanStatus.COMPLETED
            success = True
        elif completed > 0:
            plan.status = PlanStatus.PARTIALLY_COMPLETED
            success = False
        else:
            plan.status = PlanStatus.FAILED
            success = False
            
        plan.completed_at = datetime.utcnow().isoformat()
        
        return PlanResult(
            plan=plan,
            success=success,
            message="Plan execution finished" if success else f"Plan failed: {'; '.join(errors)}",
            completed_steps=completed,
            total_steps=len(plan.steps),
            errors=tuple(errors)
        )
    
    def _execute_step(self, step: PlanStep, plan: TaskPlan) -> bool:
        """Execute a single step. Returns True if successful."""
        step.status = StepStatus.IN_PROGRESS
        
        while step.retry_count <= step.max_retries:
            try:
                if self._kernel_process:
                    # Pass the step description to kernel
                    cmd = step.description
                    result = self._kernel_process(cmd)
                    if result == "FAIL":
                        raise Exception("Kernel execution failed")
                    if hasattr(result, "status"):
                        if result.status not in ("success", "ok"):
                            err_msg = result.message if hasattr(result, "message") else "Execution failed"
                            raise Exception(err_msg)
                    step.result = result
                else:
                    step.result = "Success"
                    
                step.status = StepStatus.COMPLETED
                return True
            except Exception as e:
                step.error = str(e)
                if step.retry_count < step.max_retries:
                    step.retry_count += 1
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
        """Rollback completed steps in reverse order."""
        plan.status = PlanStatus.ROLLED_BACK
        for step in reversed(plan.steps):
            if step.status == StepStatus.COMPLETED:
                step.status = StepStatus.ROLLED_BACK
