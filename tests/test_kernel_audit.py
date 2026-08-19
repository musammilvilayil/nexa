import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import (
    AuditStatus,
    ExecutionResult,
    NexaKernel,
    OperationSpec,
    RiskTier,
    SQLiteAuditLedger,
    SkillMatch,
    SkillMetadata,
    SkillRegistry,
)


class AuditDummySkill:
    def __init__(self):
        self.executions = []
        self.metadata = SkillMetadata(
            name="audit_dummy",
            version="0.1.0",
            description="audit test",
            operations=(
                OperationSpec("remember", "mutate", RiskTier.MUTATE),
                OperationSpec("publish", "remote", RiskTier.REMOTE),
            ),
        )

    def match(self, text, context):
        if text.startswith("remember "):
            return SkillMatch("audit_dummy", "remember", {"value": text.split(" ", 1)[1]})
        if text.startswith("publish "):
            return SkillMatch("audit_dummy", "publish", {"target": text.split(" ", 1)[1]})
        return None

    def validate(self, operation, params, context):
        return dict(params)

    def execute(self, operation, params, context):
        self.executions.append((operation, dict(params)))
        return ExecutionResult(True, f"{operation}:ok", data=dict(params))


class KernelAuditTests(unittest.TestCase):
    def _kernel(self, temp):
        ledger = SQLiteAuditLedger(Path(temp) / "audit.db")
        registry = SkillRegistry()
        skill = AuditDummySkill()
        registry.register(skill)
        return NexaKernel(registry=registry, audit_ledger=ledger), ledger, skill

    def test_mutating_action_is_recorded_as_success(self):
        with tempfile.TemporaryDirectory() as temp:
            kernel, ledger, _ = self._kernel(temp)
            response = kernel.process("remember hello")
            self.assertEqual(response.status, "success")
            entry = ledger.get(response.action_id)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.status, AuditStatus.SUCCESS)
            self.assertEqual(entry.operation, "remember")
            self.assertEqual(entry.params["value"], "hello")

    def test_pending_remote_action_reuses_same_audit_row_after_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            kernel, ledger, skill = self._kernel(temp)
            pending = kernel.process("publish origin")
            self.assertEqual(pending.status, "confirmation_required")
            self.assertEqual(ledger.get(pending.action_id).status, AuditStatus.PENDING)
            self.assertEqual(skill.executions, [])

            confirmed = kernel.confirm(pending.action_id)
            self.assertEqual(confirmed.status, "success")
            entry = ledger.get(pending.action_id)
            self.assertEqual(entry.status, AuditStatus.SUCCESS)
            self.assertTrue(entry.confirmed)
            self.assertEqual(len(skill.executions), 1)

    def test_secret_shaped_parameters_are_redacted(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = SQLiteAuditLedger(Path(temp) / "audit.db")
            ledger.record(
                action_id="a1",
                skill_name="teacher",
                operation="call",
                params={"api_key": "do-not-store", "prompt": "hello"},
                risk_tier="remote",
                status=AuditStatus.STARTED,
            )
            entry = ledger.get("a1")
            self.assertEqual(entry.params["api_key"], "<redacted>")
            self.assertEqual(entry.params["prompt"], "hello")


if __name__ == "__main__":
    unittest.main()
