import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import (
    ContextBus,
    ExecutionResult,
    NexaKernel,
    OperationSpec,
    RiskTier,
    SkillMatch,
    SkillMetadata,
    SkillRegistry,
)
from core.registry import RegistryError


class DummySkill:
    def __init__(self):
        self.executions = []
        self.metadata = SkillMetadata(
            name="dummy",
            version="0.1.0",
            description="Kernel contract test skill",
            operations=(
                OperationSpec("ping", "Return PONG", RiskTier.READ),
                OperationSpec("remember", "Store a test value", RiskTier.MUTATE),
                OperationSpec("publish", "Simulate remote publish", RiskTier.REMOTE),
            ),
        )

    def match(self, text, context):
        normalized = text.strip().lower()
        if normalized == "system ping":
            return SkillMatch("dummy", "ping")
        if normalized.startswith("remember "):
            return SkillMatch(
                "dummy",
                "remember",
                {"value": text.split(" ", 1)[1]},
            )
        if normalized.startswith("publish "):
            return SkillMatch(
                "dummy",
                "publish",
                {"target": text.split(" ", 1)[1]},
            )
        return None

    def validate(self, operation, params, context):
        if operation == "ping":
            return {}
        if operation == "remember":
            value = str(params.get("value", "")).strip()
            if not value:
                raise ValueError("value required")
            return {"value": value}
        if operation == "publish":
            target = str(params.get("target", "")).strip()
            if not target:
                raise ValueError("target required")
            return {"target": target}
        raise ValueError("unknown operation")

    def execute(self, operation, params, context):
        self.executions.append((operation, dict(params), dict(context)))
        if operation == "ping":
            return ExecutionResult(True, "PONG")
        if operation == "remember":
            return ExecutionResult(True, f"remembered:{params['value']}")
        if operation == "publish":
            return ExecutionResult(True, f"published:{params['target']}")
        return ExecutionResult(False, "unknown", error="unknown operation")


class KernelCoreTests(unittest.TestCase):
    def _kernel(self):
        registry = SkillRegistry()
        skill = DummySkill()
        registry.register(skill)
        return NexaKernel(registry=registry), skill

    def test_read_operation_runs_end_to_end(self):
        kernel, skill = self._kernel()

        response = kernel.process("system ping")

        self.assertEqual(response.status, "success")
        self.assertEqual(response.message, "PONG")
        self.assertEqual(skill.executions[0][0], "ping")

    def test_mutate_operation_runs_after_validation(self):
        kernel, skill = self._kernel()

        response = kernel.process("remember hello")

        self.assertEqual(response.status, "success")
        self.assertEqual(skill.executions[0][1], {"value": "hello"})

    def test_remote_operation_pauses_for_confirmation(self):
        kernel, skill = self._kernel()

        response = kernel.process("publish origin")

        self.assertEqual(response.status, "confirmation_required")
        self.assertEqual(skill.executions, [])
        self.assertIsNotNone(response.pending_action)

    def test_confirmation_executes_exact_validated_request_without_rematch(self):
        kernel, skill = self._kernel()

        pending = kernel.process("publish origin")
        action_id = pending.pending_action.action_id
        confirmed = kernel.confirm(action_id)

        self.assertEqual(confirmed.status, "success")
        self.assertEqual(skill.executions[0][0], "publish")
        self.assertEqual(skill.executions[0][1], {"target": "origin"})
        self.assertEqual(kernel.pending_actions(), ())

    def test_mutating_public_pending_view_cannot_change_internal_request(self):
        kernel, skill = self._kernel()

        pending = kernel.process("publish origin")
        pending.pending_action.params["target"] = "attacker-controlled"
        confirmed = kernel.confirm(pending.pending_action.action_id)

        self.assertEqual(confirmed.status, "success")
        self.assertEqual(skill.executions[0][1], {"target": "origin"})

    def test_pending_action_cannot_be_confirmed_twice(self):
        kernel, _ = self._kernel()

        pending = kernel.process("publish origin")
        action_id = pending.pending_action.action_id
        self.assertEqual(kernel.confirm(action_id).status, "success")
        self.assertEqual(kernel.confirm(action_id).status, "error")

    def test_unknown_input_fails_closed(self):
        kernel, skill = self._kernel()

        response = kernel.process("delete everything")

        self.assertEqual(response.status, "no_match")
        self.assertEqual(skill.executions, [])

    def test_duplicate_skill_registration_is_rejected(self):
        registry = SkillRegistry()
        registry.register(DummySkill())

        with self.assertRaisesRegex(RegistryError, "already registered"):
            registry.register(DummySkill())

    def test_context_snapshot_is_copied(self):
        bus = ContextBus()
        bus.set_session_value("user", "owner")
        snapshot = bus.snapshot()
        bus.set_session_value("user", "changed")

        self.assertEqual(snapshot.session["user"], "owner")


if __name__ == "__main__":
    unittest.main()
