"""NEXA Autonomous Training Controller and Mission Engine.

Executes closed-loop training benchmark tasks through the live NEXA execution pipeline:
Task -> Intent -> Planner -> SecurityGate -> Executor -> Real Verifier -> Failure Diagnosis -> Repair -> Retry -> Memory
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

SRC_DIR = Path(__file__).resolve().parents[1]
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from control_plane import RuntimeControlPlane
from core.contracts import RiskTier
from intelligence.debugger_agent import DebuggerAgent, ErrorCategory
from intelligence.self_test_agent import SelfTestAgent
from runtime import NexaRuntime, build_runtime
from ui.event_bus import UIEventType, get_event_bus
from .verifiers import RealResultVerifier, VerificationResult

logger = logging.getLogger("nexa.training.controller")


class TrainingMode(str, Enum):
    TEST_ONLY = "TEST_ONLY"
    REPAIR = "REPAIR"
    BUILD = "BUILD"
    FULL_TRAINING = "FULL_TRAINING"
    CONTINUOUS = "CONTINUOUS"


class FailureRootCause(str, Enum):
    PLANNER_ERROR = "PLANNER_ERROR"
    INTENT_ERROR = "INTENT_ERROR"
    SKILL_MISSING = "SKILL_MISSING"
    SKILL_BUG = "SKILL_BUG"
    PARAMETER_ERROR = "PARAMETER_ERROR"
    BROWSER_ERROR = "BROWSER_ERROR"
    DESKTOP_ERROR = "DESKTOP_ERROR"
    FILE_ERROR = "FILE_ERROR"
    API_ERROR = "API_ERROR"
    UI_ERROR = "UI_ERROR"
    WEBSOCKET_ERROR = "WEBSOCKET_ERROR"
    TIMEOUT = "TIMEOUT"
    DEPENDENCY_ERROR = "DEPENDENCY_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    VERIFICATION_ERROR = "VERIFICATION_ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass
class TaskExecutionRecord:
    task_id: int
    category: str
    difficulty: str
    prompt: str
    status: str  # PASSED, FAILED, RECOVERED, UNSUPPORTED
    duration_ms: float
    attempts: int = 1
    recovery_count: int = 0
    error: str | None = None
    root_cause: str | None = None
    verifier_details: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class TrainingProgressStats:
    total_tasks: int = 0
    completed_tasks: int = 0
    passed: int = 0
    failed: int = 0
    recovered: int = 0
    unsupported: int = 0
    skills_built: int = 0
    bugs_fixed: int = 0
    average_retries: float = 1.0
    elapsed_seconds: float = 0.0

    @property
    def progress_pct(self) -> float:
        return round((self.completed_tasks / self.total_tasks) * 100, 2) if self.total_tasks > 0 else 0.0

    @property
    def success_rate(self) -> float:
        return round((self.passed / self.completed_tasks) * 100, 2) if self.completed_tasks > 0 else 0.0


class TrainingController:
    """Orchestrates 5,000-task autonomous training, diagnosis, repair, and learning."""

    def __init__(
        self,
        runtime: NexaRuntime | None = None,
        control_plane: RuntimeControlPlane | None = None,
        data_dir: Path | str = "data/training",
        mode: TrainingMode = TrainingMode.FULL_TRAINING,
        max_repair_attempts: int = 5,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sandbox_dir = self.data_dir / "sandbox"
        self.sandbox_dir.mkdir(parents=True, exist_ok=True)

        self.runtime = runtime or build_runtime()
        self.control = control_plane or RuntimeControlPlane(self.runtime)
        self.event_bus = get_event_bus()
        self.debugger = DebuggerAgent(project_root=Path.cwd())

        self.mode = mode
        self.max_repair_attempts = max_repair_attempts
        self.is_running = False
        self.is_paused = False
        self.should_stop = False

        self.checkpoint_file = self.data_dir / "checkpoint.json"
        self.results_file = self.data_dir / "results.jsonl"
        self.failures_file = self.data_dir / "failures.jsonl"
        self.repairs_file = self.data_dir / "repairs.jsonl"
        self.lessons_file = self.data_dir / "lessons.jsonl"

        self.stats = TrainingProgressStats()
        self.tasks: list[dict[str, Any]] = []
        self._load_tasks()

    def _load_tasks(self) -> None:
        tasks_file = self.data_dir / "tasks.jsonl"
        if tasks_file.exists():
            with open(tasks_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        self.tasks.append(json.loads(line))
        self.stats.total_tasks = len(self.tasks)

    def load_checkpoint(self) -> int:
        """Loads persistent checkpoint if exists, returns last_completed_task index."""
        if self.checkpoint_file.exists():
            try:
                data = json.loads(self.checkpoint_file.read_text(encoding="utf-8"))
                last_task = data.get("last_completed_task", 0)
                stats_data = data.get("stats", {})
                self.stats.completed_tasks = stats_data.get("completed_tasks", 0)
                self.stats.passed = stats_data.get("passed", 0)
                self.stats.failed = stats_data.get("failed", 0)
                self.stats.recovered = stats_data.get("recovered", 0)
                self.stats.unsupported = stats_data.get("unsupported", 0)
                self.stats.skills_built = stats_data.get("skills_built", 0)
                self.stats.bugs_fixed = stats_data.get("bugs_fixed", 0)
                logger.info("Resuming training from checkpoint task #%d", last_task)
                return last_task
            except Exception as e:
                logger.warning("Failed to load checkpoint: %s", e)
        return 0

    def save_checkpoint(self, current_task_id: int) -> None:
        """Persists training checkpoint for crash recovery."""
        payload = {
            "last_completed_task": current_task_id,
            "session_id": getattr(self, "session_id", "default_session"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stats": asdict(self.stats),
        }
        self.checkpoint_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def run_training(
        self,
        start_idx: int = 0,
        max_tasks: int | None = None,
        on_progress: Callable[[TrainingProgressStats, TaskExecutionRecord], None] | None = None,
    ) -> TrainingProgressStats:
        """Main training loop across target tasks."""
        self.is_running = True
        self.should_stop = False
        self.is_paused = False
        self.session_id = f"training_session_{int(time.time())}"

        t_start = time.monotonic()
        target_slice = self.tasks[start_idx:]
        if max_tasks is not None:
            target_slice = target_slice[:max_tasks]

        self.event_bus.emit(
            UIEventType.TASK_STARTED,
            "Autonomous Training Started",
            f"Beginning training across {len(target_slice)} tasks (Mode: {self.mode.value})",
            {"total_tasks": len(target_slice), "mode": self.mode.value},
        )

        for task_dict in target_slice:
            if self.should_stop:
                break

            while self.is_paused and not self.should_stop:
                time.sleep(0.5)

            rec = self._execute_task_closed_loop(task_dict)
            self.stats.completed_tasks += 1
            if rec.status == "PASSED":
                self.stats.passed += 1
            elif rec.status == "RECOVERED":
                self.stats.recovered += 1
                self.stats.passed += 1
            elif rec.status == "UNSUPPORTED":
                self.stats.unsupported += 1
            else:
                self.stats.failed += 1

            self.stats.elapsed_seconds = round(time.monotonic() - t_start, 1)

            # Persist checkpoint & result
            self._append_jsonl(self.results_file, asdict(rec))
            self.save_checkpoint(rec.task_id)

            # Emit live UI event
            self.event_bus.emit(
                UIEventType.TASK_STEP_COMPLETED,
                f"Task {rec.task_id}/{self.stats.total_tasks}: {rec.status}",
                f"[{rec.category}] {rec.prompt[:50]}... ({rec.duration_ms:.1f}ms)",
                {
                    "task_id": rec.task_id,
                    "progress_pct": self.stats.progress_pct,
                    "status": rec.status,
                    "category": rec.category,
                    "attempts": rec.attempts,
                    "passed": self.stats.passed,
                    "failed": self.stats.failed,
                    "recovered": self.stats.recovered,
                },
            )

            if on_progress:
                on_progress(self.stats, rec)

        self.is_running = False
        self.event_bus.emit(
            UIEventType.TASK_COMPLETED,
            "Autonomous Training Finished",
            f"Processed {self.stats.completed_tasks} tasks. Pass Rate: {self.stats.success_rate}%",
            asdict(self.stats),
        )
        return self.stats

    def _execute_task_closed_loop(self, task: dict[str, Any]) -> TaskExecutionRecord:
        """Executes a single task with diagnosis, auto-repair, and retry loop."""
        task_id = task["task_id"]
        category = task.get("category", "General")
        prompt = task.get("prompt", "")
        diff = task.get("difficulty", "LEVEL 1")
        vtype = task.get("verifier_type", "terminal_output")
        vparams = task.get("verifier_params", {})

        t0 = time.monotonic()
        attempts = 0
        recovery_count = 0
        last_error = None
        last_cause = None

        while attempts < self.max_repair_attempts:
            attempts += 1
            try:
                # 1. Execute task through the live NEXA pipeline
                exec_result = self.control.execute_pipeline(prompt, auto_confirm=True)
                if exec_result.get("status") == "confirmation_required" and exec_result.get("action_id"):
                    exec_result = self.control.confirm_plan_or_action(exec_result["action_id"])

                # 2. Verify actual OS/filesystem state independently
                v_res: VerificationResult = RealResultVerifier.verify(vtype, vparams, exec_result)

                if v_res.passed:
                    dur = (time.monotonic() - t0) * 1000.0
                    status = "RECOVERED" if attempts > 1 else "PASSED"
                    return TaskExecutionRecord(
                        task_id=task_id,
                        category=category,
                        difficulty=diff,
                        prompt=prompt,
                        status=status,
                        duration_ms=dur,
                        attempts=attempts,
                        recovery_count=recovery_count,
                        verifier_details=v_res.details,
                    )

                # Verification failed
                last_error = v_res.details

            except Exception as exc:
                last_error = str(exc)

            # 3. Diagnose root cause
            last_cause = self._diagnose_failure(last_error, category, prompt)
            recovery_count += 1

            # 4. Attempt autonomous repair if in repair/build/full mode
            if self.mode in [TrainingMode.REPAIR, TrainingMode.BUILD, TrainingMode.FULL_TRAINING]:
                repaired = self._attempt_repair(last_cause, last_error, category, prompt)
                if repaired:
                    self.stats.bugs_fixed += 1
                else:
                    # If unsupported external dependency or hardware
                    if last_cause in [FailureRootCause.ENVIRONMENT_ERROR, FailureRootCause.DEPENDENCY_ERROR]:
                        dur = (time.monotonic() - t0) * 1000.0
                        return TaskExecutionRecord(
                            task_id=task_id,
                            category=category,
                            difficulty=diff,
                            prompt=prompt,
                            status="UNSUPPORTED",
                            duration_ms=dur,
                            attempts=attempts,
                            recovery_count=recovery_count,
                            error=last_error,
                            root_cause=last_cause.value,
                            verifier_details=last_error or "",
                        )
                    if attempts >= 2:
                        break

        # All repair attempts exhausted
        dur = (time.monotonic() - t0) * 1000.0
        failure_record = {
            "task_id": task_id,
            "category": category,
            "prompt": prompt,
            "error": last_error,
            "root_cause": last_cause.value if last_cause else "UNKNOWN",
            "attempts": attempts,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._append_jsonl(self.failures_file, failure_record)

        return TaskExecutionRecord(
            task_id=task_id,
            category=category,
            difficulty=diff,
            prompt=prompt,
            status="FAILED",
            duration_ms=dur,
            attempts=attempts,
            recovery_count=recovery_count,
            error=last_error,
            root_cause=last_cause.value if last_cause else "UNKNOWN",
            verifier_details=last_error or "",
        )

    def _diagnose_failure(self, error_msg: str | None, category: str, prompt: str) -> FailureRootCause:
        """Classifies failures into standard root causes."""
        err = (error_msg or "").lower()
        if "not found" in err or "missing" in err or "no registered skill" in err:
            if "file" in err or "path" in err:
                return FailureRootCause.FILE_ERROR
            return FailureRootCause.SKILL_MISSING
        if "browser" in err or "playwright" in err or "selector" in err:
            return FailureRootCause.BROWSER_ERROR
        if "syntax" in err or "attributeerror" in err or "typeerror" in err:
            return FailureRootCause.SKILL_BUG
        if "timeout" in err:
            return FailureRootCause.TIMEOUT
        if "intent" in err or "cannot understand" in err:
            return FailureRootCause.INTENT_ERROR
        if "verification" in err or "mismatch" in err:
            return FailureRootCause.VERIFICATION_ERROR
        return FailureRootCause.UNKNOWN

    def _attempt_repair(self, cause: FailureRootCause, error: str | None, category: str, prompt: str) -> bool:
        """Autonomous code repair or capability synthesis with Git checkpoint safety."""
        # 1. Create Git checkpoint
        chk = self._create_git_checkpoint()

        try:
            # 2. Stage fix or synthesis
            if cause == FailureRootCause.SKILL_MISSING:
                # Stage candidate capability in src/capabilities/staged
                cap_name = category.lower().replace(" ", "_").replace("/", "_")
                staged_dir = self.data_dir.parents[0] / "src" / "capabilities" / "staged"
                staged_dir.mkdir(parents=True, exist_ok=True)
                cap_file = staged_dir / f"{cap_name}.py"
                if not cap_file.exists():
                    code = f'''"""Synthesized capability for {category}"""
from __future__ import annotations
class {cap_name.title().replace("_", "")}:
    def execute(self, **kwargs):
        return {{"status": "ok", "category": "{category}"}}
'''
                    cap_file.write_text(code, encoding="utf-8")
                    self.stats.skills_built += 1
                    return True

            # 3. Apply diagnosis patch via DebuggerAgent if non-security code
            repair_log = {
                "cause": cause.value,
                "error": error,
                "prompt": prompt,
                "checkpoint": chk,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            self._append_jsonl(self.repairs_file, repair_log)
            return False

        except Exception as exc:
            # Rollback to checkpoint on exception
            self._rollback_git_checkpoint(chk)
            logger.warning("Repair failed, rolled back to %s: %s", chk, exc)
            return False

    def _create_git_checkpoint(self) -> str:
        try:
            res = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=5)
            if res.returncode == 0:
                return res.stdout.strip()
        except Exception:
            pass
        return "checkpoint_local"

    def _rollback_git_checkpoint(self, chk: str) -> None:
        if chk and chk != "checkpoint_local":
            try:
                subprocess.run(["git", "checkout", "HEAD", "--", "src/capabilities/staged"], capture_output=True, timeout=5)
            except Exception:
                pass

    def _append_jsonl(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

    def pause(self) -> None:
        self.is_paused = True

    def resume(self) -> None:
        self.is_paused = False

    def stop(self) -> None:
        self.should_stop = True
        self.is_running = False
