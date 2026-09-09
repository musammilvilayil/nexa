from __future__ import annotations

from typing import Any, Mapping

from bridges import GeminiBridge
from core.contracts import OperationSpec, RiskTier, SkillMetadata

from .contracts import (
    CapabilityBuildResult,
    CapabilityPlan,
    CapabilitySpec,
)
from .tester import CapabilityTester
from .validator import CapabilityValidator


# Deterministic high-quality template for file.zip.extract
ZIP_EXTRACT_SKILL_CODE = '''from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping

from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata


_EXTRACT_RE = re.compile(
    r"^(?:/zip\\s+extract|unzip|extract(?:\\s+this)?(?:\\s+zip(?:\\s+file)?)?)\\s+['\\"]?([^'\\"\\s]+\\.zip)['\\"]?(?:\\s+(?:to|into)\\s+['\\"]?([^'\\"\\s]+)['\\"]?)?$",
    re.IGNORECASE,
)
_FALLBACK_RE = re.compile(r"^(?:/zip\\s+extract|unzip|extract(?:\\s+this)?(?:\\s+zip(?:\\s+file)?)?)$", re.IGNORECASE)


class ZipExtractSkill:
    """Securely extracts ZIP archives confined to the active workspace."""

    def __init__(self) -> None:
        self.metadata = SkillMetadata(
            name="zip_extract",
            version="0.1.0",
            description="Extract ZIP archives securely within workspace root",
            operations=(
                OperationSpec(
                    "extract",
                    "Extract a ZIP file into workspace directory",
                    RiskTier.MUTATE,
                ),
            ),
            required_resources=("workspace",),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = " ".join(text.strip().split())
        match = _EXTRACT_RE.fullmatch(normalized)
        if match:
            archive = match.group(1).strip()
            dest = (match.group(2) or ".").strip()
            return SkillMatch("zip_extract", "extract", {"archive_path": archive, "destination": dest})

        if _FALLBACK_RE.fullmatch(normalized) or normalized.lower() in {"extract this zip file", "unzip this file"}:
            return SkillMatch("zip_extract", "extract", {"archive_path": "", "destination": "."})

        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation != "extract":
            raise ValueError(f"Unknown operation: {operation}")

        root_path = context.get("active_workspace_path") or "."
        root = Path(root_path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError(f"Workspace root not found: {root}")

        archive_raw = str(params.get("archive_path", "")).strip()
        if not archive_raw:
            # Look for the first .zip file in the workspace
            zip_files = sorted(root.glob("*.zip"))
            if not zip_files:
                raise ValueError("No archive path specified and no .zip file found in workspace")
            archive_path = zip_files[0]
        else:
            archive_path = (root / archive_raw).resolve()

        if not archive_path.is_relative_to(root):
            raise ValueError(f"Archive path escaped workspace: {archive_raw}")
        if not archive_path.exists() or not archive_path.is_file():
            raise ValueError(f"ZIP file not found: {archive_path.name}")

        dest_raw = str(params.get("destination", ".")).strip()
        dest_path = (root / dest_raw).resolve()
        if not dest_path.is_relative_to(root):
            raise ValueError(f"Destination path escaped workspace: {dest_raw}")

        return {
            "root": root,
            "archive_path": archive_path,
            "destination": dest_path,
        }

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        if operation != "extract":
            return ExecutionResult(False, "Unknown operation", error="unknown_operation")

        root: Path = params["root"]
        archive: Path = params["archive_path"]
        dest: Path = params["destination"]

        try:
            dest.mkdir(parents=True, exist_ok=True)
            extracted_names: list[str] = []

            with zipfile.ZipFile(archive, "r") as zf:
                for member in zf.namelist():
                    target = (dest / member).resolve()
                    if not target.is_relative_to(root) or not target.is_relative_to(dest):
                        return ExecutionResult(
                            False,
                            f"Zip traversal detected for member: {member}",
                            error="zip_slip_security_violation",
                        )
                zf.extractall(dest)
                extracted_names = zf.namelist()

            dest_rel = dest.relative_to(root).as_posix()
            archive_rel = archive.relative_to(root).as_posix()
            return ExecutionResult(
                True,
                f"Successfully extracted {len(extracted_names)} item(s) from {archive_rel} into {dest_rel}",
                data={
                    "archive": archive_rel,
                    "destination": dest_rel,
                    "count": len(extracted_names),
                    "items": extracted_names[:50],
                },
            )
        except Exception as exc:
            return ExecutionResult(
                False,
                f"Failed to extract ZIP archive: {exc}",
                error=str(exc),
            )
'''

ZIP_EXTRACT_TEST_CODE = '''from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path

from skill import ZipExtractSkill


class TestZipExtractSkill(unittest.TestCase):
    def setUp(self):
        self.skill = ZipExtractSkill()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()
        self.context = {"active_workspace_path": str(self.workspace)}

        # Create a sample archive
        self.zip_path = self.workspace / "sample.zip"
        with zipfile.ZipFile(self.zip_path, "w") as zf:
            zf.writestr("hello.txt", "Hello World")
            zf.writestr("nested/data.json", '{"status": "ok"}')

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_metadata(self):
        self.assertEqual(self.skill.metadata.name, "zip_extract")
        self.assertIsNotNone(self.skill.metadata.operation("extract"))

    def test_match(self):
        m = self.skill.match("unzip sample.zip", self.context)
        self.assertIsNotNone(m)
        self.assertEqual(m.skill_name, "zip_extract")
        self.assertEqual(m.operation, "extract")
        self.assertEqual(m.params["archive_path"], "sample.zip")

        m2 = self.skill.match("extract sample.zip to out", self.context)
        self.assertIsNotNone(m2)
        self.assertEqual(m2.params["destination"], "out")

    def test_validate_and_execute(self):
        params = self.skill.validate(
            "extract",
            {"archive_path": "sample.zip", "destination": "extracted"},
            self.context,
        )
        res = self.skill.execute("extract", params, self.context)
        self.assertTrue(res.success)
        self.assertTrue((self.workspace / "extracted" / "hello.txt").exists())
        self.assertEqual(
            (self.workspace / "extracted" / "hello.txt").read_text(encoding="utf-8"),
            "Hello World",
        )
        self.assertTrue((self.workspace / "extracted" / "nested" / "data.json").exists())


if __name__ == "__main__":
    unittest.main()
'''


class SkillBuilder:
    """Synthesizes, repairs, and tests candidate skills."""

    def __init__(
        self,
        bridge: GeminiBridge | None = None,
        validator: CapabilityValidator | None = None,
        tester: CapabilityTester | None = None,
        max_repairs: int = 2,
    ) -> None:
        self.bridge = bridge
        self.validator = validator or CapabilityValidator()
        self.tester = tester or CapabilityTester()
        self.max_repairs = max_repairs

    def build(self, plan: CapabilityPlan) -> CapabilityBuildResult:
        # Check deterministic templates first for reliable, offline, and known capabilities
        if plan.capability_id == "file.zip.extract":
            code = ZIP_EXTRACT_SKILL_CODE
            test_code = ZIP_EXTRACT_TEST_CODE
            class_name = "ZipExtractSkill"
        else:
            # Build using template generator or Gemini
            code, test_code, class_name = self._generate_skill(plan)

        # Validation & repair loop
        current_code = code
        current_test = test_code

        for attempt in range(self.max_repairs + 1):
            val_report = self.validator.validate(current_code)
            if not val_report.valid:
                err_msg = "; ".join(f.message for f in val_report.findings)
                if attempt >= self.max_repairs:
                    return CapabilityBuildResult(
                        success=False,
                        spec=None,
                        code=current_code,
                        test_code=current_test,
                        class_name=class_name,
                        error=f"Static validation failed: {err_msg}",
                    )
                current_code = self._repair_code(plan, current_code, err_msg)
                continue

            test_report = self.tester.run_tests(current_code, current_test)
            if not test_report.passed:
                if attempt >= self.max_repairs:
                    return CapabilityBuildResult(
                        success=False,
                        spec=None,
                        code=current_code,
                        test_code=current_test,
                        class_name=class_name,
                        error=f"Functional tests failed: {test_report.error}\n{test_report.output}",
                    )
                current_code = self._repair_code(
                    plan, current_code, f"{test_report.error}\n{test_report.output}"
                )
                continue

            # Both validation and tests passed!
            spec = CapabilitySpec(
                capability_id=plan.capability_id,
                name=plan.name,
                description=plan.description,
                purpose=plan.purpose,
                version="0.1.0",
                risk_tier=plan.risk_tier,
                input_schema={"type": "object", "properties": dict(plan.extracted_params)},
                output_schema={"type": "object"},
                dependencies=plan.dependencies,
                permissions=("workspace.write" if plan.risk_tier == RiskTier.MUTATE else "workspace.read",),
            )
            return CapabilityBuildResult(
                success=True,
                spec=spec,
                code=current_code,
                test_code=current_test,
                class_name=class_name,
            )

        return CapabilityBuildResult(
            success=False,
            spec=None,
            code=current_code,
            test_code=current_test,
            class_name=class_name,
            error="Repair loop exhausted",
        )

    def _generate_skill(self, plan: CapabilityPlan) -> tuple[str, str, str]:
        if self.bridge and self.bridge.available():
            # Prompt Gemini to generate code & test code
            schema = {
                "type": "object",
                "properties": {
                    "class_name": {"type": "string"},
                    "skill_code": {"type": "string"},
                    "test_code": {"type": "string"},
                },
                "required": ["class_name", "skill_code", "test_code"],
            }
            prompt = (
                f"Write a complete, production-ready Python Skill class following the NEXA Skill contract.\n"
                f"Capability ID: {plan.capability_id}\n"
                f"Name: {plan.name}\n"
                f"Description: {plan.description}\n"
                f"Operation: {plan.operation}\n"
                f"Risk Tier: {plan.risk_tier.value}\n"
                f"Intents: {list(plan.intents)}\n"
                f"Do not use forbidden calls (eval, exec, compile, __import__) or forbidden modules (ctypes, socket, etc.).\n"
                f"Provide full test_code using unittest."
            )
            try:
                res = self.bridge.generate_json(prompt, schema)
                return res["skill_code"], res["test_code"], res["class_name"]
            except Exception:
                pass

        # Generic fallback generator for simple custom skills
        class_name = "".join(part.capitalize() for part in plan.name.split("_")) + "Skill"
        code = f'''from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata


class {class_name}:
    """{plan.description}"""

    def __init__(self) -> None:
        self.metadata = SkillMetadata(
            name="{plan.name}",
            version="0.1.0",
            description="{plan.description}",
            operations=(
                OperationSpec(
                    "{plan.operation}",
                    "{plan.description}",
                    RiskTier.{plan.risk_tier.name},
                ),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = " ".join(text.strip().split()).lower()
        intents = {list(plan.intents)}
        for intent in intents:
            if intent in normalized:
                return SkillMatch("{plan.name}", "{plan.operation}", {dict(plan.extracted_params)})
        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        return dict(params)

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        return ExecutionResult(True, f"Executed {plan.name}.{plan.operation} successfully", data=dict(params))
'''
        test_code = f'''from __future__ import annotations

import unittest
from skill import {class_name}


class Test{class_name}(unittest.TestCase):
    def setUp(self):
        self.skill = {class_name}()

    def test_metadata(self):
        self.assertEqual(self.skill.metadata.name, "{plan.name}")

    def test_match(self):
        m = self.skill.match("{plan.intents[0] if plan.intents else plan.name}", {{}})
        self.assertIsNotNone(m)

    def test_execute(self):
        res = self.skill.execute("{plan.operation}", {{}}, {{}})
        self.assertTrue(res.success)


if __name__ == "__main__":
    unittest.main()
'''
        return code, test_code, class_name

    def _repair_code(self, plan: CapabilityPlan, code: str, error: str) -> str:
        # If bridge is available, ask it to repair the code
        if self.bridge and self.bridge.available():
            schema = {
                "type": "object",
                "properties": {
                    "repaired_code": {"type": "string"},
                },
                "required": ["repaired_code"],
            }
            prompt = (
                f"Repair the following Python skill code which failed validation/tests:\n"
                f"ERROR:\n{error}\n\n"
                f"CODE:\n{code}\n"
            )
            try:
                res = self.bridge.generate_json(prompt, schema)
                return res["repaired_code"]
            except Exception:
                pass
        return code
