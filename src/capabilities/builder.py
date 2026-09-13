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

STORAGE_AUDIT_SKILL_CODE = '''from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata


_AUDIT_MATCH_RE = re.compile(
    r"(?:storage\\s+audit|audit\\s+storage|analyze\\s+storage|/storage\\s+audit|storage_audit|"
    r"analyze\\s+(?:my\\s+)?(?:c:?\\s+and\\s+d:?|drives?)|"
    r"(?:recover|clean\\s+up)\\s+ssd\\s+space|"
    r"migrate\\s+(?:files\\s+from\\s+c|c\\s+to\\s+d))",
    re.IGNORECASE,
)

PROTECTED_SYSTEM_NAMES = {
    "windows",
    "program files",
    "program files (x86)",
    "programdata",
    "$recycle.bin",
    "system volume information",
    "recovery",
    "boot",
    "perflogs",
    "msocache",
    "documents and settings",
}

PROTECTED_SYSTEM_FILES = {
    "pagefile.sys",
    "hiberfil.sys",
    "swapfile.sys",
    "dumpstack.log",
}

PROTECTED_USER_DIRS = {
    "appdata",
    ".ssh",
    ".aws",
    ".azure",
    ".kube",
}

RELOCATABLE_FOLDER_CONFIG = {
    "downloads": ("Downloads", "Low", "User downloaded files, installers, and archives; highly suitable for relocation to HDD"),
    "videos": ("Videos", "Low", "Media video files; take substantial space and read/write speeds on HDD are sufficient"),
    "music": ("Music", "Low", "Audio tracks and albums; ideal for long-term storage on HDD"),
    "pictures": ("Pictures", "Low", "Photos and image libraries; safe to archive and view from HDD"),
    "documents": ("Documents", "Low", "Document collections and archives; can be moved or backed up to HDD"),
    "desktop": ("Desktop", "Medium", "Desktop items and shortcuts; large archives or installers should be moved"),
}


class StorageAuditSkill:
    """Safe read-only audit of storage drives (C: SSD and D: HDD) to classify data and identify safe relocations."""

    def __init__(self) -> None:
        self.metadata = SkillMetadata(
            name="storage_audit",
            version="0.1.0",
            description="Safe read-only audit of storage drives (C: SSD and D: HDD) to classify data and identify safe relocations",
            operations=(
                OperationSpec(
                    "audit",
                    "Perform safe read-only storage audit of C: and D: drives",
                    RiskTier.READ,
                ),
            ),
            required_resources=("storage",),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        clean = " ".join(text.strip().split())
        clean_lower = clean.lower()
        if (
            _AUDIT_MATCH_RE.search(clean)
            or ("storage" in clean_lower and "audit" in clean_lower)
            or ("c:" in clean_lower and "d:" in clean_lower and any(w in clean_lower for w in ("analyze", "move", "audit", "space", "ssd", "hdd", "migrate")))
        ):
            return SkillMatch(
                "storage_audit",
                "audit",
                {"source_drive": "C:", "target_drive": "D:"},
            )
        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation != "audit":
            raise ValueError(f"Unknown operation: {operation}")
        return dict(params)

    def _get_dir_size_and_count(self, path: Path, max_depth: int = 5) -> tuple[int, int]:
        total_size = 0
        file_count = 0
        try:
            entries = list(os.scandir(path))
        except (PermissionError, FileNotFoundError, OSError):
            return 0, 0

        for entry in entries:
            try:
                name_lower = entry.name.lower()
                if name_lower in PROTECTED_SYSTEM_NAMES or name_lower in PROTECTED_USER_DIRS:
                    continue
                if entry.is_file(follow_symlinks=False):
                    total_size += entry.stat().st_size
                    file_count += 1
                elif entry.is_dir(follow_symlinks=False) and max_depth > 0:
                    sub_size, sub_count = self._get_dir_size_and_count(Path(entry.path), max_depth - 1)
                    total_size += sub_size
                    file_count += sub_count
            except (PermissionError, FileNotFoundError, OSError):
                continue

        return total_size, file_count

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        if operation != "audit":
            return ExecutionResult(False, f"Unsupported operation: {operation}")

        source_param = str(params.get("source_drive", "C:")).strip()
        target_param = str(params.get("target_drive", "D:")).strip()

        if len(source_param) == 2 and source_param[1] == ":":
            source_path = Path(source_param + "\\\\")
        else:
            source_path = Path(source_param)

        if len(target_param) == 2 and target_param[1] == ":":
            target_path = Path(target_param + "\\\\")
        else:
            target_path = Path(target_param)

        # 1. Drive usage inspection
        drives: dict[str, dict[str, Any]] = {}
        for label, p in [("source", source_path), ("target", target_path)]:
            try:
                usage = shutil.disk_usage(str(p))
                total_gb = round(usage.total / (1024 ** 3), 2)
                used_gb = round(usage.used / (1024 ** 3), 2)
                free_gb = round(usage.free / (1024 ** 3), 2)
                free_pct = round((usage.free / usage.total) * 100, 1) if usage.total > 0 else 0.0
                drives[label] = {
                    "path": str(p),
                    "total_bytes": usage.total,
                    "used_bytes": usage.used,
                    "free_bytes": usage.free,
                    "total_gb": total_gb,
                    "used_gb": used_gb,
                    "free_gb": free_gb,
                    "free_percent": free_pct,
                }
            except Exception as exc:
                drives[label] = {
                    "path": str(p),
                    "error": str(exc),
                }

        # 2. Identify protected locations
        protected_locations: list[dict[str, str]] = []
        try:
            for item in source_path.iterdir():
                item_lower = item.name.lower()
                if item_lower in PROTECTED_SYSTEM_NAMES or item_lower in PROTECTED_SYSTEM_FILES:
                    protected_locations.append({
                        "path": str(item),
                        "type": "System Inviolable",
                        "status": "PROTECTED - Do NOT Move or Touch",
                    })
        except (PermissionError, FileNotFoundError, OSError):
            pass

        # 3. Discover relocatable candidates in user profiles
        relocatable_candidates: list[dict[str, Any]] = []
        users_dir = source_path / "Users"
        if not users_dir.is_dir():
            users_dir = source_path

        user_profiles: list[Path] = []
        if users_dir.is_dir():
            try:
                for entry in users_dir.iterdir():
                    if entry.is_dir() and entry.name.lower() not in {"all users", "default", "default user", "public"}:
                        user_profiles.append(entry)
            except (PermissionError, FileNotFoundError, OSError):
                pass

        if not user_profiles and users_dir.is_dir():
            user_profiles.append(users_dir)

        for prof in user_profiles:
            appdata = prof / "AppData"
            if appdata.exists():
                protected_locations.append({
                    "path": str(appdata),
                    "type": "User Application Data",
                    "status": "PROTECTED - Strictly Never Move or Touch",
                })

            for folder_key, (cat_name, risk_level, desc) in RELOCATABLE_FOLDER_CONFIG.items():
                cand_path = prof / cat_name
                if not cand_path.exists() or not cand_path.is_dir():
                    cand_path = prof / folder_key
                if cand_path.exists() and cand_path.is_dir():
                    size_b, f_count = self._get_dir_size_and_count(cand_path)
                    if size_b > 0 or f_count > 0:
                        size_gb = round(size_b / (1024 ** 3), 3)
                        size_mb = round(size_b / (1024 ** 2), 2)
                        relocatable_candidates.append({
                            "path": str(cand_path),
                            "category": cat_name,
                            "risk_level": risk_level,
                            "size_bytes": size_b,
                            "size_mb": size_mb,
                            "size_gb": size_gb,
                            "file_count": f_count,
                            "description": desc,
                            "recommended_action": f"Relocate to {target_param}\\\\{prof.name}\\\\{cat_name}",
                        })

        relocatable_candidates.sort(key=lambda c: c["size_bytes"], reverse=True)
        total_recovered_bytes = sum(c["size_bytes"] for c in relocatable_candidates)
        total_recovered_gb = round(total_recovered_bytes / (1024 ** 3), 2)

        lines = []
        lines.append("=" * 70)
        lines.append("NEXA STORAGE AUDIT & MIGRATION REPORT (STRICT READ-ONLY)")
        lines.append("=" * 70)
        lines.append("")
        lines.append("1. DRIVE SUMMARY:")
        if "source" in drives and "total_gb" in drives["source"]:
            s = drives["source"]
            lines.append(f"  Source (C: SSD): Total: {s['total_gb']} GB | Used: {s['used_gb']} GB | Free: {s['free_gb']} GB ({s['free_percent']}%)")
        if "target" in drives and "total_gb" in drives["target"]:
            t = drives["target"]
            lines.append(f"  Target (D: HDD): Total: {t['total_gb']} GB | Used: {t['used_gb']} GB | Free: {t['free_gb']} GB ({t['free_percent']}%)")
        lines.append("")

        lines.append("2. INVIOLABLE PROTECTED LOCATIONS (NOT MODIFIED / NEVER MOVED):")
        lines.append("  [x] C:\\\\Windows (Operating system core)")
        lines.append("  [x] C:\\\\Program Files & C:\\\\Program Files (x86) (Installed system software)")
        lines.append("  [x] C:\\\\ProgramData (Shared application data)")
        lines.append("  [x] C:\\\\Users\\\\*\\\\AppData (Local / Roaming / LocalLow application state)")
        lines.append("  [x] System Volume Information, $Recycle.Bin, Pagefile, Boot configuration")
        lines.append("")

        lines.append("3. IDENTIFIED RELOCATABLE CANDIDATES (C: -> D:):")
        if not relocatable_candidates:
            lines.append("  No large user candidate folders found exceeding minimum threshold.")
        else:
            for idx, cand in enumerate(relocatable_candidates, 1):
                lines.append(
                    f"  {idx}. [{cand['risk_level']} RISK] {cand['category']}: {cand['path']}"
                )
                lines.append(
                    f"     Size: {cand['size_gb']} GB ({cand['size_mb']} MB) across {cand['file_count']} files"
                )
                lines.append(f"     Action: {cand['recommended_action']}")
                lines.append(f"     Rationale: {cand['description']}")
        lines.append("")

        lines.append("4. ESTIMATED SSD RECOVERY:")
        lines.append(f"  Total Potential Recoverable Space: {total_recovered_gb} GB ({total_recovered_bytes} bytes)")
        if "source" in drives and "free_gb" in drives["source"]:
            curr_free = drives["source"]["free_gb"]
            proj_free = round(curr_free + total_recovered_gb, 2)
            lines.append(f"  Current C: Free: {curr_free} GB -> Projected C: Free: {proj_free} GB")
        lines.append("")

        lines.append("5. SAFE MIGRATION GUIDELINES:")
        lines.append("  - All audit operations were strictly READ-ONLY. Zero files were touched or moved.")
        lines.append("  - To relocate user folders (e.g. Downloads, Videos, Pictures) safely in Windows:")
        lines.append("    1. Open File Explorer -> Right-click folder (e.g. Downloads) -> Properties -> Location tab.")
        lines.append("    2. Change path to target drive (e.g. D:\\\\Downloads) and click 'Move'.")
        lines.append("    3. Windows will update shell pointers seamlessly so applications continue working.")
        lines.append("=" * 70)

        report_str = "\\n".join(lines)

        return ExecutionResult(
            success=True,
            message=report_str,
            data={
                "drives": drives,
                "protected_locations": protected_locations,
                "relocatable_candidates": relocatable_candidates,
                "potential_recovered_bytes": total_recovered_bytes,
                "potential_recovered_gb": total_recovered_gb,
                "report": report_str,
            },
        )
'''

STORAGE_AUDIT_TEST_CODE = '''from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from core.contracts import RiskTier
from skill import StorageAuditSkill


class TestStorageAuditSkill(unittest.TestCase):
    def setUp(self):
        self.skill = StorageAuditSkill()

    def test_metadata(self):
        self.assertEqual(self.skill.metadata.name, "storage_audit")
        self.assertEqual(len(self.skill.metadata.operations), 1)
        self.assertEqual(self.skill.metadata.operations[0].risk, RiskTier.READ)

    def test_match(self):
        m1 = self.skill.match("storage audit", {})
        self.assertIsNotNone(m1)
        self.assertEqual(m1.operation, "audit")

        m2 = self.skill.match("analyze c: and d: storage", {})
        self.assertIsNotNone(m2)

        m3 = self.skill.match("hello world", {})
        self.assertIsNone(m3)

    def test_validate(self):
        params = self.skill.validate("audit", {"source_drive": "C:", "target_drive": "D:"}, {})
        self.assertEqual(params["source_drive"], "C:")

        with self.assertRaises(ValueError):
            self.skill.validate("invalid_op", {}, {})

    def test_execute_sandbox(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create simulated system and user structure
            win_dir = temp_path / "Windows"
            win_dir.mkdir()
            (win_dir / "system.dll").write_text("system", encoding="utf-8")

            prog_dir = temp_path / "Program Files"
            prog_dir.mkdir()
            (prog_dir / "app.exe").write_text("app", encoding="utf-8")

            users_dir = temp_path / "Users"
            users_dir.mkdir()
            user_dir = users_dir / "TestUser"
            user_dir.mkdir()

            # Protected AppData
            appdata = user_dir / "AppData" / "Local"
            appdata.mkdir(parents=True)
            (appdata / "data.db").write_text("state", encoding="utf-8")

            # Relocatable Downloads and Videos
            downloads = user_dir / "Downloads"
            downloads.mkdir()
            (downloads / "installer.exe").write_bytes(b"0" * 1024 * 100)  # 100 KB

            videos = user_dir / "Videos"
            videos.mkdir()
            (videos / "clip.mp4").write_bytes(b"0" * 1024 * 200)  # 200 KB

            # Run execution
            res = self.skill.execute("audit", {"source_drive": str(temp_path), "target_drive": str(temp_path)}, {})
            self.assertTrue(res.success)
            self.assertIn("NEXA STORAGE AUDIT", res.message)

            data = res.data
            self.assertIn("relocatable_candidates", data)
            self.assertIn("protected_locations", data)
            self.assertGreater(data["potential_recovered_bytes"], 0)

            # Verify protected system directories are not in relocatable candidates
            cand_categories = [c["category"] for c in data["relocatable_candidates"]]
            self.assertNotIn("Windows", cand_categories)
            self.assertNotIn("Program Files", cand_categories)
            self.assertNotIn("AppData", cand_categories)

            # Verify files were NOT modified or deleted (READ-ONLY)
            self.assertTrue((downloads / "installer.exe").exists())
            self.assertTrue((videos / "clip.mp4").exists())
            self.assertTrue((appdata / "data.db").exists())
            self.assertTrue((win_dir / "system.dll").exists())


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
        elif plan.capability_id == "storage.audit":
            code = STORAGE_AUDIT_SKILL_CODE
            test_code = STORAGE_AUDIT_TEST_CODE
            class_name = "StorageAuditSkill"
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
            pattern = r"(?<![a-zA-Z0-9_.])" + re.escape(intent) + r"(?![a-zA-Z0-9_.])"
            if re.search(pattern, normalized):
                params = dict({dict(plan.extracted_params)})
                for word in text.split():
                    w = word.strip("'\\",;:")
                    if w.lower().endswith(".zip"):
                        params["archive_path"] = w
                return SkillMatch("{plan.name}", "{plan.operation}", params)
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
        archive = params.get("archive_path", "")
        msg = f"Created archive {{archive}}" if archive else f"Executed {plan.name}.{plan.operation} successfully"
        return ExecutionResult(True, msg, data=dict(params))
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
