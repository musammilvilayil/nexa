from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from planner.contracts import PlanStep, TaskPlan, PlanResult, PlanStatus, StepStatus
from planner.task_planner import TaskPlanner
from planner.executor import PlanExecutor
from planner.composer import SkillComposer

class TestTaskPlanner(unittest.TestCase):
    def test_plan_step_creation(self):
        step = PlanStep(step_id=1, description="test", skill_name="test_skill", operation="test_op")
        self.assertEqual(step.step_id, 1)
        self.assertEqual(step.status, StepStatus.PENDING)
        
    def test_task_plan_creation(self):
        plan = TaskPlan(plan_id="1", description="test")
        self.assertEqual(plan.plan_id, "1")
        self.assertEqual(plan.status, PlanStatus.PENDING)
        
    def test_plan_result_creation(self):
        plan = TaskPlan(plan_id="1", description="test")
        res = PlanResult(plan=plan, success=True, message="done")
        self.assertTrue(res.success)
        
    def test_plan_status_enum(self):
        self.assertEqual(PlanStatus.PENDING, "pending")
        self.assertEqual(PlanStatus.COMPLETED, "completed")
        self.assertEqual(PlanStatus.FAILED, "failed")
        
    def test_step_status_enum(self):
        self.assertEqual(StepStatus.PENDING, "pending")
        self.assertEqual(StepStatus.SKIPPED, "skipped")
        self.assertEqual(StepStatus.COMPLETED, "completed")
        
    def test_planner_single_step_plan(self):
        planner = TaskPlanner()
        plan = planner.plan("single request")
        self.assertEqual(len(plan.steps), 1)
        self.assertEqual(plan.description, "single request")
        
    def test_executor_executes_steps_in_order(self):
        plan = TaskPlan(plan_id="1", description="test", steps=[
            PlanStep(step_id=1, description="s1", skill_name="s", operation="o"),
            PlanStep(step_id=2, description="s2", skill_name="s", operation="o", depends_on=(1,))
        ])
        
        executor = PlanExecutor()
        res = executor.execute(plan)
        
        self.assertTrue(res.success)
        self.assertEqual(res.completed_steps, 2)
        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)
        self.assertEqual(plan.steps[1].status, StepStatus.COMPLETED)
        
    def test_executor_skips_failed_dependencies(self):
        plan = TaskPlan(plan_id="1", description="test", steps=[
            PlanStep(step_id=1, description="s1", skill_name="s", operation="o"),
            PlanStep(step_id=2, description="s2", skill_name="s", operation="o", depends_on=(1,))
        ])
        
        def mock_kernel(req):
            return "FAIL"
            
        executor = PlanExecutor(kernel_process=mock_kernel)
        res = executor.execute(plan)
        
        self.assertFalse(res.success)
        self.assertEqual(plan.steps[0].status, StepStatus.FAILED)
        self.assertEqual(plan.steps[1].status, StepStatus.SKIPPED)
        
    def test_executor_retries_on_failure(self):
        plan = TaskPlan(plan_id="1", description="test", steps=[
            PlanStep(step_id=1, description="s1", skill_name="s", operation="o", max_retries=2)
        ])
        
        tries = 0
        def flacky_kernel(req):
            nonlocal tries
            tries += 1
            if tries < 2:
                return "FAIL"
            return "SUCCESS"
            
        executor = PlanExecutor(kernel_process=flacky_kernel)
        res = executor.execute(plan)
        
        self.assertTrue(res.success)
        self.assertEqual(plan.steps[0].retry_count, 1)
        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)

    def test_composer_save_and_retrieve(self):
        composer = SkillComposer()
        plan = TaskPlan(plan_id="1", description="test")
        composer.save_workflow("flow1", plan)
        
        retrieved = composer.get_workflow("flow1")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.description, "test")
        self.assertIsNot(plan, retrieved)
        
    def test_composer_list_workflows(self):
        composer = SkillComposer()
        composer.save_workflow("flow1", TaskPlan(plan_id="1", description="test"))
        self.assertEqual(composer.list_workflows(), ["flow1"])
        
    def test_plan_result_success(self):
        plan = TaskPlan(plan_id="1", description="test", steps=[])
        res = PlanResult(plan=plan, success=True, message="msg")
        self.assertTrue(res.success)

if __name__ == "__main__":
    unittest.main()
