from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from capabilities import (
    CapabilityEventType,
    CapabilityManager,
    CapabilityPlan,
    CapabilityPlanner,
    CapabilityRecord,
    CapabilitySpec,
    CapabilityStore,
    CapabilityTester,
    CapabilityValidator,
    SkillBuilder,
)
from core.contracts import RiskTier
from core.registry import SkillRegistry


class CapabilityLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name).resolve()
        self.db_path = self.root / "test_capabilities.db"
        self.storage_dir = self.root / "capabilities"
        self.store = CapabilityStore(self.db_path)
        self.validator = CapabilityValidator()
        self.tester = CapabilityTester()
        self.builder = SkillBuilder(validator=self.validator, tester=self.tester)
        self.planner = CapabilityPlanner()
        self.manager = CapabilityManager(
            store=self.store,
            planner=self.planner,
            builder=self.builder,
            storage_dir=self.storage_dir,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_store_persistence_and_versioning(self):
        spec = CapabilitySpec(
            capability_id="test.tool.echo",
            name="echo_tool",
            description="Simple echo tool",
            purpose="Testing persistence",
            version="0.1.0",
            risk_tier=RiskTier.READ,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            dependencies=("typing",),
            permissions=(),
        )
        record = CapabilityRecord(
            spec=spec,
            module_path=str(self.storage_dir / "echo" / "skill.py"),
            class_name="EchoSkill",
            test_status="passed",
            created_at_utc="2026-09-10T00:00:00Z",
            updated_at_utc="2026-09-10T00:00:00Z",
        )
        self.store.save_capability(record, code="# code", test_code="# test")

        fetched = self.store.get_capability("test.tool.echo")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.spec.name, "echo_tool")
        self.assertEqual(fetched.usage_count, 0)

        self.store.record_usage("test.tool.echo")
        updated = self.store.get_capability("test.tool.echo")
        self.assertEqual(updated.usage_count, 1)
        self.assertIsNotNone(updated.last_used_at_utc)

    def test_observability_events(self):
        self.manager.log_event(
            CapabilityEventType.CAPABILITY_REQUESTED,
            "test.tool",
            "Checking request",
            {"detail": 123},
        )
        events = self.store.get_events(limit=10)
        self.assertTrue(len(events) >= 1)
        self.assertEqual(events[0].event_type, CapabilityEventType.CAPABILITY_REQUESTED)
        self.assertEqual(events[0].capability_id, "test.tool")
        self.assertEqual(events[0].details.get("detail"), 123)

    def test_validator_blocks_unsafe_code(self):
        unsafe_code = """
import socket
from core.contracts import ExecutionResult

class EvilSkill:
    def match(self, text, context):
        return None
    def validate(self, op, params, context):
        return {}
    def execute(self, op, params, context):
        eval("1+1")
        return ExecutionResult(True, "hacked")
"""
        report = self.validator.validate(unsafe_code)
        self.assertFalse(report.valid)
        rule_names = [f.rule for f in report.findings]
        self.assertIn("forbidden_import", rule_names)
        self.assertIn("forbidden_call", rule_names)

    def test_validator_accepts_valid_skill(self):
        safe_code = """from __future__ import annotations
from typing import Any, Mapping
from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata

class SafeSkill:
    def __init__(self):
        self.metadata = SkillMetadata(
            name="safe",
            version="0.1.0",
            description="Safe skill",
            operations=(OperationSpec("run", "Safe run", RiskTier.READ),),
        )
    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        return SkillMatch("safe", "run") if text == "safe" else None
    def validate(self, op: str, params: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        return {}
    def execute(self, op: str, params: Mapping[str, Any], context: Mapping[str, Any]) -> ExecutionResult:
        return ExecutionResult(True, "all good")
"""
        report = self.validator.validate(safe_code)
        self.assertTrue(report.valid)
        self.assertEqual(report.class_name, "SafeSkill")

    def test_planner_gap_detection(self):
        plan = self.planner.detect_gap("extract archive.zip to out", {})
        self.assertIsNotNone(plan)
        self.assertEqual(plan.capability_id, "file.zip.extract")
        self.assertEqual(plan.operation, "extract")
        self.assertEqual(plan.extracted_params["archive_path"], "archive.zip")

        non_gap = self.planner.detect_gap("what is the capital of France?", {})
        self.assertIsNone(non_gap)

    def test_builder_builds_zip_extract(self):
        plan = self.planner.detect_gap("extract test.zip", {})
        self.assertIsNotNone(plan)
        res = self.builder.build(plan)
        self.assertTrue(res.success)
        self.assertIsNotNone(res.spec)
        self.assertEqual(res.spec.name, "zip_extract")
        self.assertIn("ZipExtractSkill", res.code)


if __name__ == "__main__":
    unittest.main()
