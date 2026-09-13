from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agents.contracts import AgentResult, AgentRole
from agents.orchestrator import SupervisorOrchestrator
from core.contracts import RiskTier
from core.security import SecurityGate
from extensions.contracts import ExtensionStatus
from extensions.multi_agent_extension import MultiAgentExtension


class TestLevel5MultiAgent(unittest.TestCase):
    def setUp(self):
        self.gate = SecurityGate()
        self.orchestrator = SupervisorOrchestrator(security_gate=self.gate)
        self.ext = MultiAgentExtension(security_gate=self.gate)

    def test_workers_registered_and_roles(self):
        workers = self.orchestrator.list_workers()
        roles = [w["role"] for w in workers]
        self.assertIn("planner", roles)
        self.assertIn("research", roles)
        self.assertIn("browser", roles)
        self.assertIn("desktop", roles)
        self.assertIn("coder", roles)
        self.assertIn("verifier", roles)
        self.assertIn("security", roles)

    def test_privilege_escalation_blocked(self):
        # PLANNER (READ only) attempts to delegate CRITICAL action to CODER
        res = self.orchestrator.delegate(
            from_agent=AgentRole.PLANNER,
            to_agent=AgentRole.CODER,
            instruction="Execute live financial trade",
            max_risk=RiskTier.CRITICAL,
        )
        self.assertFalse(res.success)
        self.assertEqual(res.error, "privilege_escalation_blocked")
        self.assertIn("Privilege escalation blocked", res.output)

    def test_security_gate_denial(self):
        # Deny list pattern in delegation
        res = self.orchestrator.delegate(
            from_agent=AgentRole.SUPERVISOR,
            to_agent=AgentRole.CODER,
            instruction="rm -rf / --no-preserve-root",
            max_risk=RiskTier.DESTRUCTIVE,
            confirmed=True,
        )
        self.assertFalse(res.success)
        self.assertIn("SecurityGate", res.output)

    def test_security_gate_confirmation_required(self):
        # REMOTE risk unconfirmed requires confirmation
        res_unconfirmed = self.orchestrator.delegate(
            from_agent=AgentRole.SUPERVISOR,
            to_agent=AgentRole.RESEARCH,
            instruction="Search sensitive external URL",
            max_risk=RiskTier.REMOTE,
            confirmed=False,
        )
        self.assertFalse(res_unconfirmed.success)
        self.assertEqual(res_unconfirmed.error, "confirmation_required")

        # Confirmed succeeds
        res_confirmed = self.orchestrator.delegate(
            from_agent=AgentRole.SUPERVISOR,
            to_agent=AgentRole.RESEARCH,
            instruction="Search sensitive external URL",
            max_risk=RiskTier.REMOTE,
            confirmed=True,
        )
        self.assertTrue(res_confirmed.success)
        self.assertIn("Research completed", res_confirmed.output)

    def test_supervisor_orchestration_flow(self):
        goal = "Build user login widget with security checks"
        res = self.orchestrator.orchestrate(goal)
        self.assertTrue(res.success)
        self.assertIn("Supervisor orchestration succeeded", res.output)
        self.assertTrue(res.data.get("verified"))

    def test_supervisor_conflict_resolution(self):
        res1 = AgentResult(success=True, output="Code written", role=AgentRole.CODER)
        res2 = AgentResult(success=False, output="Verification tests failed", error="test_fail", role=AgentRole.VERIFIER)

        arbitration = self.orchestrator.resolve_conflicts([res1, res2])
        self.assertFalse(arbitration.success)
        self.assertIn("Rejected due to failures", arbitration.output)

    def test_multi_agent_extension_lifecycle(self):
        self.assertTrue(self.ext.initialize())
        hc = self.ext.health_check()
        self.assertEqual(hc["status"], ExtensionStatus.ACTIVE.value)
        self.assertGreaterEqual(hc["worker_count"], 7)

        run_res = self.ext.orchestrate("Quick research and verify")
        self.assertTrue(run_res["success"])

        self.assertTrue(self.ext.shutdown())
        self.assertEqual(self.ext.health_check()["status"], ExtensionStatus.STOPPED.value)


if __name__ == "__main__":
    unittest.main()
