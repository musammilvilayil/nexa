from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.contracts import RiskTier
from core.observability import ObservabilityEngine


class TestLevel5Observability(unittest.TestCase):
    def setUp(self):
        self.obs = ObservabilityEngine()

    def test_log_activity_and_metrics(self):
        evt1 = self.obs.log_activity("task", "execute_step", {"step": 1}, duration_ms=45.2)
        self.assertEqual(evt1.category, "task")
        self.assertEqual(evt1.status, "success")

        evt2 = self.obs.log_activity("task", "execute_step", {"step": 2}, duration_ms=54.8, status="failed")

        history = self.obs.get_recent_activity(category="task")
        self.assertEqual(len(history), 2)

        metrics = self.obs.get_metrics_summary()
        self.assertIn("task.execute_step", metrics)
        m = metrics["task.execute_step"]
        self.assertEqual(m["count"], 2)
        self.assertEqual(m["error_count"], 1)
        self.assertEqual(m["avg_latency_ms"], 50.0)

    def test_security_audit_logging(self):
        self.obs.log_security_decision(
            skill_name="terminal",
            operation="bash",
            risk=RiskTier.CRITICAL,
            outcome="require_confirmation",
            reason="CRITICAL action requires confirmation",
        )
        audit = self.obs.get_security_audit()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["risk_tier"], "critical")
        self.assertEqual(audit[0]["outcome"], "require_confirmation")

    def test_decision_explainability(self):
        self.obs.record_decision_rationale(
            identifier="task_123",
            goal="Open browser and extract news",
            chosen_path="BrowserSkill.open -> BrowserSkill.extract",
            considered_options=["Terminal curl", "Playwright Browser"],
            reasoning="Playwright supports dynamic JavaScript rendering required for news portal.",
        )
        exp = self.obs.explain_decision("task_123")
        self.assertEqual(exp["identifier"], "task_123")
        self.assertIn("Playwright", exp["reasoning"])
        self.assertEqual(len(exp["considered_options"]), 2)

    def test_health_summary(self):
        self.obs.log_activity("tool", "call", duration_ms=10.0, status="success")
        self.obs.log_activity("tool", "call", duration_ms=15.0, status="success")
        h = self.obs.health_summary()
        self.assertTrue(h["healthy"])
        self.assertEqual(h["success_rate"], 100.0)


if __name__ == "__main__":
    unittest.main()
