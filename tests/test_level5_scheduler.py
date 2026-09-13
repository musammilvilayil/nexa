from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.contracts import RiskTier
from core.security import SecurityGate
from extensions.contracts import ExtensionStatus
from extensions.scheduler_extension import SchedulerExtension, ScheduleType
from planner.contracts import PlanStep, StepStatus, TaskPlan, TaskRecord
from planner.executor import PlanExecutor
from planner.long_running import (
    LongRunningTaskManager,
    LongRunningTaskState,
    TaskPriority,
)
from planner.task_store import TaskStore


class TestLevel5SchedulerAndLongRunning(unittest.TestCase):
    def setUp(self):
        self.task_store = TaskStore(":memory:")
        self.executor = PlanExecutor(
            kernel_process=lambda cmd: type("Resp", (), {"status": "ok", "message": f"Ran {cmd}"})(),
            task_store=self.task_store,
        )
        self.mgr = LongRunningTaskManager(self.executor, self.task_store)
        self.gate = SecurityGate()
        self.scheduler = SchedulerExtension(
            db_path=":memory:",
            security_gate=self.gate,
        )

    def test_long_running_task_lifecycle(self):
        steps = [
            PlanStep(step_id=1, description="Step 1", skill_name="app", operation="open", params={"app_name": "notepad"}),
            PlanStep(step_id=2, description="Step 2", skill_name="app", operation="close", params={"app_name": "notepad"}),
        ]
        plan = TaskPlan(plan_id="p1", description="Test Lifecycle", steps=steps)

        task = self.mgr.submit_task("Test Goal", plan, priority=TaskPriority.HIGH)
        self.assertEqual(task.state, LongRunningTaskState.PENDING)
        self.assertEqual(task.priority, TaskPriority.HIGH)

        # Step 1
        more = self.mgr.step_task("p1")
        self.assertTrue(more)
        prog = self.mgr.get_progress("p1")
        self.assertEqual(prog.current_step, 1)
        self.assertEqual(prog.total_steps, 2)
        self.assertEqual(prog.percent, 50.0)

        # Step 2
        more = self.mgr.step_task("p1")
        self.assertFalse(more)
        task_done = self.mgr.get_task("p1")
        self.assertEqual(task_done.state, LongRunningTaskState.COMPLETED)
        self.assertEqual(len(task_done.checkpoints), 3)  # Submit + Step 1 + Step 2

    def test_long_running_task_pause_and_resume(self):
        steps = [
            PlanStep(step_id=1, description="Step 1", skill_name="app", operation="open"),
            PlanStep(step_id=2, description="Step 2", skill_name="app", operation="open"),
        ]
        plan = TaskPlan(plan_id="p_pause", description="Pause Plan", steps=steps)
        self.mgr.submit_task("Goal", plan)

        # Step 1
        self.mgr.step_task("p_pause")
        self.assertEqual(self.mgr.get_task("p_pause").current_step_idx, 1)

        # Pause
        ok = self.mgr.pause_task("p_pause")
        self.assertTrue(ok)
        self.assertEqual(self.mgr.get_task("p_pause").state, LongRunningTaskState.PAUSED)

        # Cannot step when paused
        more = self.mgr.step_task("p_pause")
        self.assertFalse(more)
        self.assertEqual(self.mgr.get_task("p_pause").current_step_idx, 1)

        # Resume
        ok = self.mgr.resume_task("p_pause")
        self.assertTrue(ok)
        self.assertEqual(self.mgr.get_task("p_pause").state, LongRunningTaskState.PENDING)

        # Continue step 2
        more = self.mgr.step_task("p_pause")
        self.assertFalse(more)
        self.assertEqual(self.mgr.get_task("p_pause").state, LongRunningTaskState.COMPLETED)

    def test_long_running_task_recovery_from_store(self):
        # Directly insert an interrupted task record in TaskStore
        plan = TaskPlan(plan_id="p_interrupted", description="Interrupted Plan", steps=[PlanStep(step_id=1, description="S1", skill_name="app", operation="open")])
        rec = TaskRecord(
            task_id="p_interrupted",
            goal="Interrupted Goal",
            plan=plan,
            current_step=1,
            state="in_progress",
        )
        self.task_store.save_task(rec)

        # System starts up and recovers
        recovered = self.mgr.recover_interrupted_tasks()
        self.assertEqual(len(recovered), 1)
        self.assertEqual(recovered[0].task_id, "p_interrupted")
        self.assertEqual(recovered[0].state, LongRunningTaskState.PAUSED)

    def test_scheduler_lifecycle_and_interval(self):
        self.assertTrue(self.scheduler.initialize())
        self.assertEqual(self.scheduler.health_check()["status"], ExtensionStatus.ACTIVE.value)

        triggered_jobs = []
        self.scheduler.executor_callback = lambda j: triggered_jobs.append(j.job_id)

        # Schedule interval job due immediately (negative interval offset for test)
        job = self.scheduler.schedule_interval("Heartbeat", 0.01, "Send Ping")
        job.next_run_at = time.time() - 1.0  # Due now
        self.scheduler._persist_job(job)

        # Tick
        fired = self.scheduler.tick()
        self.assertIn(job.job_id, fired)
        self.assertIn(job.job_id, triggered_jobs)
        self.assertEqual(job.run_count, 1)
        self.assertTrue(job.next_run_at > time.time())

        # Pause and Tick
        self.scheduler.pause_job(job.job_id)
        job.next_run_at = time.time() - 1.0
        fired2 = self.scheduler.tick()
        self.assertEqual(fired2, [])

        # Cancel
        self.assertTrue(self.scheduler.cancel_job(job.job_id))
        self.assertIsNone(self.scheduler.get_job(job.job_id))

        self.assertTrue(self.scheduler.shutdown())
        self.assertEqual(self.scheduler.health_check()["status"], ExtensionStatus.STOPPED.value)


if __name__ == "__main__":
    unittest.main()
