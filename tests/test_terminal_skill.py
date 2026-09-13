from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from skills.terminal_skill import TerminalSkill, SAFE_COMMANDS, DENY_COMMANDS


class TerminalSkillTests(unittest.TestCase):
    """Tests for the TerminalSkill."""

    def setUp(self) -> None:
        self.skill = TerminalSkill()

    # ── Metadata ──────────────────────────────────────────────────────

    def test_metadata_name(self) -> None:
        self.assertEqual(self.skill.metadata.name, "terminal")

    def test_metadata_has_run_and_run_safe(self) -> None:
        op_names = {op.name for op in self.skill.metadata.operations}
        self.assertIn("run", op_names)
        self.assertIn("run_safe", op_names)

    # ── Match ─────────────────────────────────────────────────────────

    def test_match_run_command(self) -> None:
        match = self.skill.match("run echo hello", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.params["command"], "echo hello")

    def test_match_terminal_run(self) -> None:
        match = self.skill.match("/terminal echo hello", {})
        self.assertIsNotNone(match)

    def test_match_execute(self) -> None:
        match = self.skill.match("execute dir", {})
        self.assertIsNotNone(match)

    def test_match_safe_command_classified(self) -> None:
        match = self.skill.match("run dir", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "run_safe")

    def test_match_unsafe_command_classified(self) -> None:
        match = self.skill.match("run unknown_tool --flag", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "run")

    def test_match_no_match(self) -> None:
        match = self.skill.match("hello world", {})
        self.assertIsNone(match)

    # ── Validate ──────────────────────────────────────────────────────

    def test_validate_empty_command_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.skill.validate("run", {"command": ""}, {})

    def test_validate_null_bytes_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.skill.validate("run", {"command": "echo \x00"}, {})

    def test_validate_denied_command_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.skill.validate("run", {"command": "format C:"}, {})

    def test_validate_diskpart_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.skill.validate("run", {"command": "diskpart"}, {})

    def test_validate_destructive_pattern_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.skill.validate("run", {"command": "rm -rf /"}, {})

    def test_validate_secret_exposure_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.skill.validate("run", {"command": "echo API_KEY=abc123"}, {})

    def test_validate_safe_command_passes(self) -> None:
        result = self.skill.validate("run_safe", {"command": "echo hello"}, {})
        self.assertEqual(result["command"], "echo hello")

    def test_validate_long_command_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.skill.validate("run", {"command": "x" * 10_001}, {})

    # ── Classify ──────────────────────────────────────────────────────

    def test_safe_commands_include_git(self) -> None:
        self.assertIn("git", SAFE_COMMANDS)

    def test_safe_commands_include_python(self) -> None:
        self.assertIn("python", SAFE_COMMANDS)

    def test_deny_commands_include_format(self) -> None:
        self.assertIn("format", DENY_COMMANDS)

    def test_deny_commands_include_shutdown(self) -> None:
        self.assertIn("shutdown", DENY_COMMANDS)

    # ── Execute ───────────────────────────────────────────────────────

    def test_execute_success_mock(self) -> None:
        self.skill._bridge = MagicMock()
        self.skill._bridge.run.return_value = {
            "stdout": "hello\n",
            "stderr": "",
            "returncode": 0,
        }
        result = self.skill.execute(
            "run_safe",
            {"command": "echo hello", "base_command": "echo", "timeout": 60.0},
            {},
        )
        self.assertTrue(result.success)
        self.assertEqual(result.data["exit_code"], 0)

    def test_execute_failure_mock(self) -> None:
        self.skill._bridge = MagicMock()
        self.skill._bridge.run.return_value = {
            "stdout": "",
            "stderr": "command not found",
            "returncode": 127,
        }
        result = self.skill.execute(
            "run",
            {"command": "unknown_cmd", "base_command": "unknown_cmd", "timeout": 60.0},
            {},
        )
        self.assertFalse(result.success)
        self.assertEqual(result.data["exit_code"], 127)

    def test_output_truncation(self) -> None:
        skill = TerminalSkill(max_output_bytes=1000)
        long_text = "x" * 5000
        truncated = skill._truncate(long_text)
        self.assertIn("truncated", truncated)
        self.assertLess(len(truncated), len(long_text))


if __name__ == "__main__":
    unittest.main()
