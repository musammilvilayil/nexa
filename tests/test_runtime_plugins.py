import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import ContextBus
from runtime import build_runtime
from skills.file_skill import FileSkill
from skills.github_skill import GitHubSkill
from skills.workspace_skill import WorkspaceSkill
from workspace import WorkspaceManager


class WorkspacePluginTests(unittest.TestCase):
    def _repo(self, root: Path, name: str) -> Path:
        repo = root / name
        repo.mkdir(parents=True)
        (repo / ".git").mkdir()
        return repo.resolve()

    def test_switch_updates_context_bus(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            repo = self._repo(root, "alpha")
            manager = WorkspaceManager([root])
            bus = ContextBus()
            skill = WorkspaceSkill(manager, bus)

            match = skill.match("repo alpha switch cheyyu", {})
            self.assertIsNotNone(match)
            params = skill.validate(match.operation, match.params, {})
            result = skill.execute(match.operation, params, {})

            self.assertTrue(result.success)
            self.assertEqual(bus.snapshot().active_workspace_path, str(repo))


class FilePluginTests(unittest.TestCase):
    def test_file_read_write_patch_stays_inside_active_workspace(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            context = {"active_workspace_path": str(root)}
            skill = FileSkill(max_read_bytes=10_000, max_write_bytes=10_000)

            write = skill.validate("write", {"path": "notes/a.txt", "content": "hello"}, context)
            self.assertTrue(skill.execute("write", write, context).success)

            read = skill.validate("read", {"path": "notes/a.txt"}, context)
            self.assertEqual(skill.execute("read", read, context).data, "hello")

            patch_params = skill.validate(
                "patch",
                {"path": "notes/a.txt", "old": "hello", "new": "world"},
                context,
            )
            self.assertTrue(skill.execute("patch", patch_params, context).success)
            self.assertEqual((root / "notes" / "a.txt").read_text(encoding="utf-8"), "world")

            with self.assertRaisesRegex(ValueError, "inside active workspace"):
                skill.validate("read", {"path": "../escape.txt"}, context)

    def test_patch_requires_exactly_one_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            target = root / "a.txt"
            target.write_text("x x", encoding="utf-8")
            context = {"active_workspace_path": str(root)}
            skill = FileSkill()
            params = skill.validate("patch", {"path": "a.txt", "old": "x", "new": "y"}, context)
            result = skill.execute("patch", params, context)
            self.assertFalse(result.success)
            self.assertIn("exactly one", result.message)


class RuntimeBuilderTests(unittest.TestCase):
    def test_runtime_registers_kernel_plugins_and_defaults_to_research(self):
        with tempfile.TemporaryDirectory() as temp:
            audit = Path(temp) / "actions.db"
            with patch.dict(
                os.environ,
                {
                    "NEXA_AUDIT_DB": str(audit),
                    "NEXA_TRADING_MODE": "research",
                    "NEXA_TRADING_SYMBOLS": "NIFTY50",
                },
                clear=False,
            ):
                runtime = build_runtime()

            names = tuple(item.name for item in runtime.registry.list_metadata())
            self.assertIn("workspace", names)
            self.assertIn("files", names)
            self.assertIn("git", names)
            self.assertIn("github", names)
            self.assertIn("trading", names)
            self.assertIsInstance(runtime.github_skill, GitHubSkill)
            self.assertEqual(runtime.trading_skill.mandate.mode.value, "research")
            self.assertTrue(audit.exists())


if __name__ == "__main__":
    unittest.main()
