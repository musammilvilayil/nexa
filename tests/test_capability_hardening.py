from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from capabilities.contracts import (
    CapabilityEventType,
    CapabilityRecord,
    CapabilitySpec,
)
from capabilities.manager import CapabilityManager
from capabilities.store import CapabilityStore
from core.contracts import RiskTier, Skill, SkillMetadata
from core.registry import SkillRegistry


class DummyMockSkill(Skill):
    def __init__(self, name: str = "test_cap") -> None:
        self._name = name

    @property
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name=self._name,
            version="1.0.0",
            description="Dummy skill for testing",
            operations=(),
        )

    def match(self, text: str, context: dict):
        return None

    def validate(self, match: Any) -> bool:
        return True

    def execute(self, match: Any, context: dict):
        raise NotImplementedError


class CapabilityHardeningTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.db_path = self.root / "caps.db"
        self.storage_dir = self.root / "caps_code"
        self.store = CapabilityStore(self.db_path)
        self.manager = CapabilityManager(
            store=self.store,
            storage_dir=self.storage_dir,
            max_failures_before_disable=3,
        )
        self.registry = SkillRegistry()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_health_check_initial_and_success(self):
        health = self.manager.get_capability_health("cap_alpha")
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["failure_count"], 0)
        self.assertEqual(health["success_count"], 0)
        self.assertFalse(health["is_disabled"])

        self.manager.record_execution("cap_alpha", success=True)
        health_after = self.manager.get_capability_health("cap_alpha")
        self.assertEqual(health_after["status"], "healthy")
        self.assertEqual(health_after["success_count"], 1)
        self.assertEqual(health_after["failure_count"], 0)

    def test_failure_tracking_degraded_and_auto_disable(self):
        skill = DummyMockSkill("cap_beta")
        self.registry.register(skill)
        self.manager._loaded_skills["cap_beta"] = skill
        self.assertTrue(self.registry.has_skill("cap_beta"))

        # 1 failure -> degraded
        self.manager.record_execution("cap_beta", success=False, error="Error 1", registry=self.registry)
        health1 = self.manager.get_capability_health("cap_beta")
        self.assertEqual(health1["status"], "degraded")
        self.assertEqual(health1["failure_count"], 1)
        self.assertFalse(health1["is_disabled"])
        self.assertTrue(self.registry.has_skill("cap_beta"))

        # 2 failures -> degraded
        self.manager.record_execution("cap_beta", success=False, error="Error 2", registry=self.registry)
        health2 = self.manager.get_capability_health("cap_beta")
        self.assertEqual(health2["status"], "degraded")
        self.assertEqual(health2["failure_count"], 2)

        # 3 failures -> threshold reached -> auto-disable
        self.manager.record_execution("cap_beta", success=False, error="Error 3", registry=self.registry)
        health3 = self.manager.get_capability_health("cap_beta")
        self.assertEqual(health3["status"], "disabled")
        self.assertEqual(health3["failure_count"], 3)
        self.assertTrue(health3["is_disabled"])
        # Verify unregistered from registry
        self.assertFalse(self.registry.has_skill("cap_beta"))

    def test_enable_and_disable_manual(self):
        self.manager.disable_capability("cap_gamma")
        self.assertTrue(self.manager.get_capability_health("cap_gamma")["is_disabled"])

        self.manager.enable_capability("cap_gamma")
        health = self.manager.get_capability_health("cap_gamma")
        self.assertFalse(health["is_disabled"])
        self.assertEqual(health["status"], "healthy")
        self.assertEqual(health["failure_count"], 0)


if __name__ == "__main__":
    unittest.main()
