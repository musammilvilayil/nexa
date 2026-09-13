import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import NexaKernel, SkillRegistry
from skills.dummy_skill import DummySkill


class DummySkillRuntimeTests(unittest.TestCase):
    def _kernel(self):
        registry = SkillRegistry()
        registry.register(DummySkill())
        return NexaKernel(registry=registry)

    def test_ping_runs_through_registered_plugin(self):
        response = self._kernel().process("system ping")
        self.assertEqual(response.status, "success")
        self.assertEqual(response.message, "PONG")

    def test_mutate_demo_runs_after_validation(self):
        response = self._kernel().process("remember hello")
        self.assertEqual(response.status, "success")
        self.assertEqual(response.message, "remembered:hello")

    def test_remote_demo_requires_confirmation(self):
        kernel = self._kernel()
        pending = kernel.process("publish origin")
        self.assertEqual(pending.status, "confirmation_required")
        self.assertIsNotNone(pending.pending_action)

        confirmed = kernel.confirm(pending.pending_action.action_id)
        self.assertEqual(confirmed.status, "success")
        self.assertEqual(confirmed.message, "published:origin")


if __name__ == "__main__":
    unittest.main()
