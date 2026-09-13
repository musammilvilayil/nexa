import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import AuditStatus, NexaKernel, SQLiteAuditLedger, SkillRegistry
from skills.dummy_skill import DummySkill


class KernelPendingLifecycleTests(unittest.TestCase):
    def _kernel(self, now_holder, *, ledger=None):
        registry = SkillRegistry()
        registry.register(DummySkill())
        return NexaKernel(
            registry=registry,
            audit_ledger=ledger,
            pending_ttl_seconds=5,
            clock=lambda: now_holder[0],
        )

    def test_pending_action_expires_and_cannot_execute(self):
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        kernel = self._kernel(now)
        pending = kernel.process("publish origin")
        self.assertEqual(pending.status, "confirmation_required")
        action_id = pending.pending_action.action_id

        now[0] += timedelta(seconds=6)
        result = kernel.confirm(action_id)

        self.assertEqual(result.status, "expired")
        self.assertEqual(kernel.pending_actions(), ())

    def test_pending_action_can_be_cancelled_once(self):
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        kernel = self._kernel(now)
        pending = kernel.process("publish origin")
        action_id = pending.pending_action.action_id

        cancelled = kernel.cancel(action_id)
        second = kernel.cancel(action_id)

        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(second.status, "error")

    def test_pending_action_records_exact_risk_and_expiry(self):
        now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
        kernel = self._kernel(now)
        pending = kernel.process("publish origin")
        action = pending.pending_action

        self.assertEqual(action.risk.value, "remote")
        self.assertEqual(action.created_at_utc, now[0])
        self.assertEqual(action.expires_at_utc, now[0] + timedelta(seconds=5))

    def test_expiry_and_cancellation_have_terminal_audit_states(self):
        with tempfile.TemporaryDirectory() as temp:
            ledger = SQLiteAuditLedger(Path(temp) / "audit.db")
            now = [datetime(2026, 1, 1, tzinfo=timezone.utc)]
            kernel = self._kernel(now, ledger=ledger)

            cancelled_pending = kernel.process("publish cancel-me")
            cancelled_id = cancelled_pending.pending_action.action_id
            kernel.cancel(cancelled_id)
            cancelled_entry = ledger.get(cancelled_id)
            self.assertIsNotNone(cancelled_entry)
            self.assertEqual(cancelled_entry.status, AuditStatus.CANCELLED)

            expiring_pending = kernel.process("publish expire-me")
            expiring_id = expiring_pending.pending_action.action_id
            now[0] += timedelta(seconds=6)
            expired = kernel.confirm(expiring_id)
            self.assertEqual(expired.status, "expired")
            expired_entry = ledger.get(expiring_id)
            self.assertIsNotNone(expired_entry)
            self.assertEqual(expired_entry.status, AuditStatus.EXPIRED)


if __name__ == "__main__":
    unittest.main()
