from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from core.contracts import PolicyOutcome, RiskTier
from core.security import SecurityGate


class SecurityGateExpandedTests(unittest.TestCase):
    """Tests for the expanded SecurityGate with CRITICAL tier and deny list."""

    def setUp(self) -> None:
        self.gate = SecurityGate()

    # ── Backward compatibility ────────────────────────────────────────

    def test_read_is_allowed(self) -> None:
        decision = self.gate.decide(RiskTier.READ)
        self.assertEqual(decision.outcome, PolicyOutcome.ALLOW)

    def test_mutate_is_allowed(self) -> None:
        decision = self.gate.decide(RiskTier.MUTATE)
        self.assertEqual(decision.outcome, PolicyOutcome.ALLOW)

    def test_remote_requires_confirmation(self) -> None:
        decision = self.gate.decide(RiskTier.REMOTE)
        self.assertEqual(decision.outcome, PolicyOutcome.REQUIRE_CONFIRMATION)

    def test_remote_confirmed_is_allowed(self) -> None:
        decision = self.gate.decide(RiskTier.REMOTE, confirmed=True)
        self.assertEqual(decision.outcome, PolicyOutcome.ALLOW)

    def test_destructive_requires_confirmation(self) -> None:
        decision = self.gate.decide(RiskTier.DESTRUCTIVE)
        self.assertEqual(decision.outcome, PolicyOutcome.REQUIRE_CONFIRMATION)

    def test_destructive_confirmed_is_allowed(self) -> None:
        decision = self.gate.decide(RiskTier.DESTRUCTIVE, confirmed=True)
        self.assertEqual(decision.outcome, PolicyOutcome.ALLOW)

    # ── CRITICAL tier ─────────────────────────────────────────────────

    def test_critical_requires_confirmation(self) -> None:
        decision = self.gate.decide(RiskTier.CRITICAL)
        self.assertEqual(decision.outcome, PolicyOutcome.REQUIRE_CONFIRMATION)
        self.assertIn("CRITICAL", decision.reason)

    def test_critical_confirmed_is_allowed(self) -> None:
        decision = self.gate.decide(RiskTier.CRITICAL, confirmed=True)
        self.assertEqual(decision.outcome, PolicyOutcome.ALLOW)

    def test_critical_cooldown_default(self) -> None:
        self.assertEqual(self.gate.critical_cooldown_seconds, 5.0)

    def test_critical_cooldown_custom(self) -> None:
        gate = SecurityGate(critical_cooldown_seconds=10.0)
        self.assertEqual(gate.critical_cooldown_seconds, 10.0)

    def test_critical_cooldown_tracking(self) -> None:
        self.gate.record_critical_confirmation("action123")
        remaining = self.gate.check_critical_cooldown("action123")
        self.assertGreater(remaining, 0.0)

    def test_critical_cooldown_untracked_action(self) -> None:
        remaining = self.gate.check_critical_cooldown("unknown")
        self.assertEqual(remaining, 0.0)

    def test_critical_cooldown_clear(self) -> None:
        self.gate.record_critical_confirmation("action123")
        self.gate.clear_critical_confirmation("action123")
        remaining = self.gate.check_critical_cooldown("action123")
        self.assertEqual(remaining, 0.0)

    # ── Deny list ─────────────────────────────────────────────────────

    def test_deny_list_format_c(self) -> None:
        result = self.gate.check_deny_list("format C:")
        self.assertIsNotNone(result)
        self.assertEqual(result.outcome, PolicyOutcome.DENY)

    def test_deny_list_rm_rf(self) -> None:
        result = self.gate.check_deny_list("rm -rf /")
        self.assertIsNotNone(result)
        self.assertEqual(result.outcome, PolicyOutcome.DENY)

    def test_deny_list_shutdown(self) -> None:
        result = self.gate.check_deny_list("shutdown /s")
        self.assertIsNotNone(result)
        self.assertEqual(result.outcome, PolicyOutcome.DENY)

    def test_deny_list_diskpart(self) -> None:
        result = self.gate.check_deny_list("run diskpart")
        self.assertIsNotNone(result)
        self.assertEqual(result.outcome, PolicyOutcome.DENY)

    def test_deny_list_bcdedit(self) -> None:
        result = self.gate.check_deny_list("execute bcdedit command")
        self.assertIsNotNone(result)
        self.assertEqual(result.outcome, PolicyOutcome.DENY)

    def test_deny_list_safe_command_not_denied(self) -> None:
        result = self.gate.check_deny_list("open chrome")
        self.assertIsNone(result)

    def test_deny_list_normal_text_not_denied(self) -> None:
        result = self.gate.check_deny_list("search google for jobs")
        self.assertIsNone(result)

    def test_deny_list_case_insensitive(self) -> None:
        result = self.gate.check_deny_list("FORMAT C:")
        self.assertIsNotNone(result)

    def test_deny_list_custom_patterns(self) -> None:
        gate = SecurityGate(deny_patterns=[r"\bdangerous\b"])
        result = gate.check_deny_list("run dangerous command")
        self.assertIsNotNone(result)
        self.assertEqual(result.outcome, PolicyOutcome.DENY)

    def test_deny_list_empty_patterns_allows_everything(self) -> None:
        gate = SecurityGate(deny_patterns=[])
        result = gate.check_deny_list("format C:")
        self.assertIsNone(result)

    # ── Kernel integration (deny in process) ──────────────────────────

    def test_kernel_denies_blocked_text(self) -> None:
        from core import NexaKernel, SkillRegistry

        kernel = NexaKernel(
            registry=SkillRegistry(),
            security_gate=self.gate,
        )
        response = kernel.process("format C:")
        self.assertEqual(response.status, "denied")
        self.assertIn("deny list", response.message)

    def test_kernel_allows_normal_text(self) -> None:
        from core import NexaKernel, SkillRegistry

        kernel = NexaKernel(
            registry=SkillRegistry(),
            security_gate=self.gate,
        )
        # No skill matches, but deny list should not trigger
        response = kernel.process("open chrome")
        self.assertEqual(response.status, "no_match")


if __name__ == "__main__":
    unittest.main()
