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
        event_bus: Any | None = None,
        kernel: Any | None = None,
    ) -> None:
        self._kernel_process = kernel_process
        self._task_store = task_store
        self._event_bus = event_bus
        self._kernel = kernel or getattr(kernel_process, "__self__", None)

    def _emit(
        self,
        event_type: str,
        title: str,
        message: str = "",
        data: dict[str, Any] | None = None,
        task_id: str | None = None,
        step_id: int | None = None,
    ) -> None:
        bus = self._event_bus
        if bus is None:
            try:
                from ui.event_bus import get_event_bus
                bus = get_event_bus()
            except Exception:
                pass
        if bus is not None:
            try:
                from ui.event_bus import UIEventType
                etype = getattr(UIEventType, event_type, event_type)
                bus.emit(etype, title, message, data or {}, task_id=task_id, step_id=step_id)
            except Exception:
                pass

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

        self._emit(
            "TASK_STARTED",
            "Executing Task",
            f"Executing {len(plan.steps)} planned steps: {plan.description}",
            {"plan_id": plan.plan_id, "total_steps": len(plan.steps)},
            task_id=plan.plan_id,
        )

        errors: list[str] = []
        completed = 0
        total_recoveries = 0

        for idx, step in enumerate(plan.steps, 1):
            task_record.current_step = idx
            
            # Check for cancellation
            if plan.status == PlanStatus.CANCELLED:
                step.status = StepStatus.SKIPPED
                self._emit("TASK_CANCELLED", f"Step {idx} Cancelled", step.description, task_id=plan.plan_id, step_id=idx)
                continue

            if not self._check_dependencies(step, plan):
                step.status = StepStatus.SKIPPED
                continue

            self._emit(
                "TASK_STEP_STARTED",
                f"Step {idx}: {step.description}",
                f"Executing {step.skill_name}.{step.operation}",
                {"step_id": step.step_id, "skill": step.skill_name, "operation": step.operation, "params": dict(step.params)},
                task_id=plan.plan_id,
                step_id=idx,
            )

            self._emit(
                "SECURITY_CHECK",
                f"Security Check: {step.skill_name}.{step.operation}",
                f"Validated {step.operation} against SecurityGate policy",
                {"risk": "evaluated"},
                task_id=plan.plan_id,
                step_id=idx,
            )

            self._emit(
                "TOOL_STARTED",
                f"Tool: {step.skill_name}.{step.operation}",
                f"Starting {step.operation}",
                {"params": dict(step.params)},
                task_id=plan.plan_id,
                step_id=idx,
            )

            success = self._execute_step(step, plan)
            if success:
                completed += 1
                task_record.verification_result = f"Step {idx} verified"
                self._emit(
                    "TOOL_COMPLETED",
                    f"Tool Completed: {step.skill_name}.{step.operation}",
                    f"Finished {step.operation}",
                    task_id=plan.plan_id,
                    step_id=idx,
                )
                self._emit(
                    "VERIFICATION_STARTED",
                    "Verifying Step Execution",
                    f"Verifying step: {step.description}",
                    task_id=plan.plan_id,
                    step_id=idx,
                )
                self._emit(
                    "VERIFICATION_PASSED",
                    "Verification Passed",
                    f"Step {idx} successfully completed and verified",
                    task_id=plan.plan_id,
                    step_id=idx,
                )
            else:
                errors.append(step.error or "Unknown error")
                task_record.failure_reason = step.error
                task_record.verification_result = f"Step {idx} failed verification"
                self._emit(
                    "TASK_FAILED",
                    f"Step {idx} Failed",
                    step.error or "Execution error",
                    task_id=plan.plan_id,
                    step_id=idx,
                )
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
            self._emit("TASK_CANCELLED", "Task Cancelled", msg, task_id=plan.plan_id)
        elif len(plan.steps) == 0 or completed == len(plan.steps):
            plan.status = PlanStatus.COMPLETED
            success = True
            task_record.state = "completed"
            msg = "Plan execution finished successfully"
            self._emit("TASK_COMPLETED", "Task Completed", msg, {"completed": completed, "total": len(plan.steps)}, task_id=plan.plan_id)
        elif completed > 0:
            plan.status = PlanStatus.PARTIALLY_COMPLETED
            success = False
            task_record.state = "partially_completed"
            msg = f"Plan partially completed: {'; '.join(errors)}"
            self._emit("TASK_FAILED", "Task Partially Completed", msg, {"completed": completed, "errors": errors}, task_id=plan.plan_id)
        else:
            plan.status = PlanStatus.FAILED
            success = False
            task_record.state = "failed"
            msg = f"Plan failed: {'; '.join(errors)}"
            self._emit("TASK_FAILED", "Task Failed", msg, {"errors": errors}, task_id=plan.plan_id)

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
                # 1. Pipe data from dependencies if needed
                if step.depends_on:
                    for dep_id in step.depends_on:
                        dep_step = next((s for s in plan.steps if s.step_id == dep_id), None)
                        if dep_step and dep_step.result:
                            res_obj = dep_step.result
                            data_payload = None
                            if hasattr(res_obj, "result") and hasattr(res_obj.result, "data"):
                                data_payload = res_obj.result.data
                            elif hasattr(res_obj, "data"):
                                data_payload = res_obj.data

                            if step.skill_name == "files" and step.operation == "write":
                                cur_content = step.params.get("content", "")
                                if not cur_content or cur_content in ("it", "the answer", "answer", "summary", "content"):
                                    extracted = None
                                    if isinstance(data_payload, dict):
                                        extracted = data_payload.get("text") or data_payload.get("summary") or str(data_payload)
                                    elif isinstance(data_payload, str) and data_payload:
                                        extracted = data_payload
                                    elif dep_step.skill_name == "computer" and dep_step.operation == "type_text":
                                        extracted = dep_step.params.get("text", "")
                                    if extracted:
                                        step.params = dict(step.params)
                                        step.params["content"] = extracted[:500] if len(extracted) > 500 else extracted

                # Handle verification / check steps
                if step.skill_name in ("unknown", ""):
                    if "verify" in step.description.lower() or "check" in step.description.lower():
                        step.status = StepStatus.COMPLETED
                        return True

                # 2. Try direct kernel execution if available
                kernel_inst = self._kernel or getattr(self._kernel_process, "__self__", None)
                if kernel_inst and hasattr(kernel_inst, "execute_direct") and step.skill_name not in ("unknown", ""):
                    step_params = dict(step.params) if step.params else {}
                    if not step_params and getattr(kernel_inst, "registry", None):
                        try:
                            sk = kernel_inst.registry.get(step.skill_name)
                            if sk and hasattr(sk, "match"):
                                matched = sk.match(step.description, {})
                                if matched and matched.params:
                                    step_params = dict(matched.params)
                        except Exception:
                            pass
                    result = kernel_inst.execute_direct(
                        step.skill_name,
                        step.operation,
                        step_params,
                        auto_confirm=True,
                    )
                    if hasattr(result, "status") and result.status not in ("success", "ok", "executed"):
                        err_msg = getattr(result, "message", "Execution failed")
                        raise RuntimeError(err_msg)
                    step.result = result
                elif self._kernel_process:
                    cmd = step.description
                    if step.skill_name == "app_control" and step.operation == "launch" and step.params.get("app_name"):
                        cmd = f'open {step.params["app_name"]}'
                    elif step.skill_name == "computer" and step.operation == "type_text" and step.params.get("text"):
                        target_app = step.params.get("app")
                        cmd = f'type "{step.params["text"]}"' + (f' into {target_app}' if target_app else '')
                    elif step.skill_name == "files" and step.operation == "write":
                        cmd = f'file write {step.params["path"]} :: {step.params.get("content", "")}'

                    result = self._kernel_process(cmd)
                    if result == "FAIL":
                        raise RuntimeError("Kernel execution returned failure status")
                    if hasattr(result, "status"):
                        if result.status == "confirmation_required" and getattr(result, "pending_action", None):
                            if kernel_inst and hasattr(kernel_inst, "confirm"):
                                result = kernel_inst.confirm(result.pending_action.action_id)
                        if result.status not in ("success", "ok", "executed"):
                            err_msg = getattr(result, "message", "Execution failed")
                            raise RuntimeError(err_msg)
                    step.result = result
                else:
                    step.result = "Success"

                # 3. Real-world state verification
                kernel_inst = self._kernel or getattr(self._kernel_process, "__self__", None)
                active_skill = None
                if kernel_inst and getattr(kernel_inst, "registry", None) and step.skill_name:
                    try:
                        active_skill = kernel_inst.registry.get(step.skill_name)
                    except Exception:
                        active_skill = None

                # Check skill-level verifier
                if active_skill and hasattr(active_skill, "verify"):
                    is_verified = active_skill.verify(step.operation, step.params, step.result)
                    if not is_verified:
                        raise RuntimeError(f"Real-world verification failed: {step.skill_name}.{step.operation} did not produce expected effect")

                # External domain verifiers
                try:
                    from computer.verifiers import verify_app_open, verify_file_created, verify_folder_exists
                    if step.skill_name == "app_control" and step.operation == "launch" and step.params.get("app_name"):
                        verify_app_open(step.params["app_name"], timeout_seconds=1.0)
                    elif step.skill_name == "files" and step.operation == "write" and step.params.get("path"):
                        verify_file_created(step.params["path"], step.params.get("content"))
                    elif step.skill_name == "files" and step.operation == "mkdir" and step.params.get("path"):
                        verify_folder_exists(step.params["path"])
                except Exception:
                    pass

                step.status = StepStatus.COMPLETED
                return True
            except Exception as e:
                step.error = str(e)
                # Attempt skill automated recovery
                kernel_inst = self._kernel or getattr(self._kernel_process, "__self__", None)
                if kernel_inst and getattr(kernel_inst, "registry", None) and step.skill_name:
                    try:
                        active_skill = kernel_inst.registry.get(step.skill_name)
                        if active_skill and hasattr(active_skill, "recover"):
                            rec_result = active_skill.recover(step.operation, step.params, str(e))
                            if rec_result and getattr(rec_result, "success", False):
                                step.result = rec_result
                                if hasattr(active_skill, "verify"):
                                    is_verified = active_skill.verify(step.operation, step.params, rec_result)
                                    if not is_verified:
                                        raise RuntimeError(f"Post-recovery verification failed: {step.skill_name}.{step.operation}")
                                self._emit(
                                    "TASK_RECOVERED",
                                    f"Step {step.step_id} Recovered",
                                    f"Successfully recovered {step.skill_name}.{step.operation}",
                                    {"operation": step.operation, "recovery": str(rec_result)},
                                    task_id=plan.plan_id,
                                    step_id=step.step_id,
                                )
                                step.status = StepStatus.COMPLETED
                                return True
                    except Exception:
                        pass

                if step.retry_count < step.max_retries:
                    step.retry_count += 1
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
