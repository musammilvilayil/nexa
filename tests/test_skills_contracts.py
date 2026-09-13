import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from skills.contracts import BaseSkill, EnhancedOperationSpec, ParameterDefinition
from planner.contracts import TaskPlan, PlanStep, StepStatus
from planner.executor import PlanExecutor


class DummyTestingSkill(BaseSkill):
    def __init__(self):
        super().__init__(
            name='test_skill',
            version='1.0.0',
            description='Test skill for contract verification',
            operations=(
                EnhancedOperationSpec(
                    name='ping',
                    description='Ping operation',
                    risk=RiskTier.READ,
                    parameters=(
                        ParameterDefinition('msg', required=True, default='pong'),
                    ),
                    recovery_strategies=('retry_with_default',),
                ),
                EnhancedOperationSpec(
                    name='flaky_op',
                    description='Flaky operation that recovers',
                    risk=RiskTier.MUTATE,
                    parameters=(),
                ),
            ),
        )
        self.flaky_attempt = 0
        self.verified_calls = []

    def match(self, text, context):
        if 'ping' in text.lower():
            return SkillMatch('test_skill', 'ping', {'msg': 'pong'})
        return None

    def execute(self, operation, params, context):
        if operation == 'ping':
            return ExecutionResult(True, 'Pong: ' + params.get('msg', 'pong'))
        if operation == 'flaky_op':
            self.flaky_attempt += 1
            if self.flaky_attempt == 1:
                raise RuntimeError('Simulated transient network timeout')
            return ExecutionResult(True, 'Flaky op executed successfully')
        raise ValueError('Unknown op: ' + operation)

    def verify(self, operation, params, result, context=None):
        self.verified_calls.append((operation, params, result))
        if operation == 'unverifiable':
            return False
        return True

    def recover(self, operation, params, error, context=None):
        if operation == 'flaky_op':
            return self.execute(operation, params, context or {})
        return None


class TestSkillsContracts(unittest.TestCase):
    def setUp(self):
        self.skill = DummyTestingSkill()

    def test_parameter_validation_success(self):
        cleaned = self.skill.validate('ping', {'msg': 'custom_hello'}, {})
        self.assertEqual(cleaned['msg'], 'custom_hello')

    def test_parameter_validation_default_fallback(self):
        cleaned = self.skill.validate('ping', {}, {})
        self.assertEqual(cleaned['msg'], 'pong')

    def test_parameter_validation_unknown_op(self):
        with self.assertRaises(ValueError):
            self.skill.validate('nonexistent', {}, {})

    def test_execute_success(self):
        res = self.skill.execute('ping', {'msg': 'test'}, {})
        self.assertTrue(res.success)
        self.assertIn('Pong: test', res.message)

    def test_run_self_tests(self):
        results = self.skill.run_self_tests()
        self.assertTrue(results.get('test_skill_metadata_valid'))

    def test_executor_integrates_skill_verification_and_recovery(self):
        mock_registry = MagicMock()
        mock_registry.get.return_value = self.skill

        mock_kernel = MagicMock()
        mock_kernel.registry = mock_registry
        mock_kernel.execute_direct.side_effect = lambda sk, op, p, **kw: self.skill.execute(op, p, {})

        executor = PlanExecutor(kernel_process=mock_kernel.execute_direct, kernel=mock_kernel)

        plan = TaskPlan(
            plan_id='test_plan',
            description='Test recovery workflow',
            steps=[
                PlanStep(
                    step_id=1,
                    description='run flaky operation',
                    skill_name='test_skill',
                    operation='flaky_op',
                    params={},
                    max_retries=1,
                )
            ],
            original_request='run flaky operation',
            created_at='now',
        )

        result = executor.execute(plan)
        self.assertTrue(result.success, 'PlanExecutor should succeed via skill.recover()')
        self.assertEqual(plan.steps[0].status, StepStatus.COMPLETED)
        self.assertEqual(len(self.skill.verified_calls), 1)


if __name__ == '__main__':
    unittest.main()
