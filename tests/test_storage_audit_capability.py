from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from capabilities.builder import SkillBuilder
from capabilities.contracts import CapabilityEventType
from capabilities.manager import CapabilityManager
from capabilities.planner import CapabilityPlanner
from capabilities.store import CapabilityStore
from capabilities.tester import CapabilityTester
from capabilities.validator import CapabilityValidator
from core.contracts import RiskTier
from core.registry import SkillRegistry
from core.security import SecurityGate


class TestStorageAuditCapabilityLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="nexa-storage-audit-test-")
        self.temp_path = Path(self.temp_dir)
        self.store_db = self.temp_path / "capabilities.db"
        self.store = CapabilityStore(self.store_db)
        self.planner = CapabilityPlanner()
        self.validator = CapabilityValidator()
        self.tester = CapabilityTester()
        self.builder = SkillBuilder(
            validator=self.validator,
            tester=self.tester,
        )
        self.cap_storage = self.temp_path / "caps"
        self.manager = CapabilityManager(
            self.store,
            planner=self.planner,
            builder=self.builder,
            storage_dir=self.cap_storage,
        )
        self.registry = SkillRegistry()
        self.security = SecurityGate()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_planner_detects_storage_audit_gap(self):
        prompts = [
            "storage audit",
            "audit storage",
            "analyze c: and d: storage",
            "please run a storage audit",
            "/storage audit",
            "analyze c: and d: and recover ssd space",
        ]
        for prompt in prompts:
            plan = self.planner.detect_gap(prompt, {})
            self.assertIsNotNone(plan, f"Failed to detect gap for: {prompt}")
            self.assertEqual(plan.capability_id, "storage.audit")
            self.assertEqual(plan.name, "storage_audit")
            self.assertEqual(plan.operation, "audit")
            self.assertEqual(plan.risk_tier, RiskTier.READ)

    def test_builder_builds_and_sandbox_tests_storage_audit(self):
        plan = self.planner.detect_gap("storage audit analyze c: and d:", {})
        self.assertIsNotNone(plan)

        build_res = self.builder.build(plan)
        self.assertTrue(build_res.success, f"Build failed: {build_res.error}")
        self.assertIsNotNone(build_res.spec)
        self.assertEqual(build_res.spec.capability_id, "storage.audit")
        self.assertEqual(build_res.spec.risk_tier, RiskTier.READ)
        self.assertEqual(build_res.class_name, "StorageAuditSkill")

        # Static AST validation check
        report = self.validator.validate(build_res.code)
        self.assertTrue(report.valid, f"Validation findings: {report.findings}")

    def test_end_to_end_manager_gap_lifecycle(self):
        skill = self.manager.handle_gap("storage audit analyze c: and d:", {}, self.registry)
        self.assertIsNotNone(skill)
        self.assertEqual(skill.metadata.name, "storage_audit")
        self.assertEqual(skill.metadata.operations[0].risk, RiskTier.READ)

        # Confirm registered in registry
        registered_skill = self.registry.get("storage_audit")
        self.assertIsNotNone(registered_skill)

        # Confirm persisted in store
        record = self.store.get_capability("storage.audit")
        self.assertIsNotNone(record)
        self.assertEqual(record.test_status, "passed")
        self.assertTrue(Path(record.module_path).is_file())

        # SecurityGate authorization check (RiskTier.READ auto-allows)
        sec_result = self.security.decide(skill.metadata.operations[0].risk)
        self.assertEqual(sec_result.outcome.name, "ALLOW")

        # Execute read-only audit in mock simulated environment
        sim_root = self.temp_path / "sim_drive"
        sim_root.mkdir()
        (sim_root / "Windows").mkdir()
        (sim_root / "Windows" / "win.dll").write_text("sys", encoding="utf-8")

        user_dir = sim_root / "Users" / "Musammil"
        (user_dir / "AppData" / "Local").mkdir(parents=True)
        (user_dir / "AppData" / "Local" / "app.dat").write_text("data", encoding="utf-8")

        downloads = user_dir / "Downloads"
        downloads.mkdir(parents=True)
        (downloads / "big_installer.exe").write_bytes(b"x" * (1024 * 50))

        exec_res = registered_skill.execute("audit", {"source_drive": str(sim_root), "target_drive": str(sim_root)}, {})
        self.assertTrue(exec_res.success)
        self.assertIn("NEXA STORAGE AUDIT", exec_res.message)
        self.assertIn("Downloads", exec_res.message)
        self.assertGreater(exec_res.data["potential_recovered_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
