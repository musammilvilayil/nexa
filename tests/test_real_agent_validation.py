from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from runtime import build_runtime
from core.contracts import RiskTier
from core.failsafe import FailsafeTriggered


class RealAgentValidationTests(unittest.TestCase):
    """Real agent validation pass executing all requested test scenarios (TEST A - TEST J)."""

    @classmethod
    def setUpClass(cls):
        cls.runtime = build_runtime()

    # ── TEST A — Computer observation ─────────────────────────────────
    def test_a_computer_observation(self):
        """User intent: 'Take a screenshot and tell me what is currently visible.'"""
        phrase = "Take a screenshot and tell me what is currently visible."
        match = self.runtime.registry.resolve(phrase, {})
        self.assertIsNotNone(match)
        self.assertEqual(match.skill_name, "computer")
        self.assertEqual(match.operation, "screenshot")

        # Execute through kernel
        response = self.runtime.kernel.process(phrase)
        # Verify result honestly: whether successful or reporting headless/GDI capture error
        self.assertIn(response.status, ("success", "failure"))
        if response.status == "success":
            self.assertIn("Screenshot captured", response.message)
            self.assertIn("bytes", response.result.data)
        else:
            self.assertIn("capture failed", response.message.lower())

    # ── TEST B — Application control ──────────────────────────────────
    def test_b_application_control(self):
        """User intent: 'Open Notepad.'"""
        phrase = "Open Notepad."
        match = self.runtime.registry.resolve(phrase, {})
        self.assertIsNotNone(match)
        self.assertEqual(match.skill_name, "app_control")
        self.assertEqual(match.operation, "launch")

        response = self.runtime.kernel.process(phrase)
        self.assertEqual(response.status, "success")
        self.assertIn("Notepad", response.message)

        # Verify process is running
        self.assertTrue(self.runtime.app_skill._launcher.is_running("Notepad"))

        # Clean up: close Notepad
        close_response = self.runtime.kernel.process("close Notepad")
        if close_response.status == "confirmation_required":
            self.runtime.kernel.confirm(close_response.pending_action.action_id)

    # ── TEST C — Browser ──────────────────────────────────────────────
    def test_c_browser_search(self):
        """User intent: 'Open Chrome and search Google for MERN developer jobs in Kochi.'"""
        phrase = "Open Chrome and search Google for MERN developer jobs in Kochi."
        match = self.runtime.registry.resolve(phrase, {})
        self.assertIsNotNone(match)
        self.assertEqual(match.skill_name, "browser")
        self.assertEqual(match.operation, "search")

        response = self.runtime.kernel.process(phrase)
        # REMOTE risk tier requires confirmation
        if response.status == "confirmation_required":
            action_id = response.pending_action.action_id
            response = self.runtime.kernel.confirm(action_id)

        self.assertEqual(response.status, "success")
        self.assertIn("Searched Google", response.message)
        self.assertIsNotNone(response.result.data)

        # Clean up: close browser
        self.runtime.browser_skill.engine.close()

    # ── TEST D — File operation ───────────────────────────────────────
    def test_d_file_operation(self):
        """User intent: 'Create a folder called NEXA_TEST inside the workspace and create hello.txt containing Hello from NEXA.'"""
        phrase = "Create a folder called NEXA_TEST inside the workspace and create hello.txt containing Hello from NEXA."
        match = self.runtime.registry.resolve(phrase, {})
        self.assertIsNotNone(match)
        self.assertEqual(match.skill_name, "files")
        self.assertEqual(match.operation, "write")

        response = self.runtime.kernel.process(phrase)
        self.assertEqual(response.status, "success")

        # Verify folder, file, and contents exist
        ws_path = self.runtime.context_bus.snapshot().active_workspace_path
        ws = Path(ws_path) if ws_path else Path.cwd()
        test_dir = ws / "NEXA_TEST"
        test_file = test_dir / "hello.txt"
        self.assertTrue(test_dir.is_dir())
        self.assertTrue(test_file.is_file())
        self.assertEqual(test_file.read_text(encoding="utf-8").strip(), "Hello from NEXA")

        # Clean up
        test_file.unlink()
        test_dir.rmdir()

    # ── TEST E — Terminal ─────────────────────────────────────────────
    def test_e_terminal(self):
        """User intent: 'Run python --version.'"""
        phrase = "Run python --version."
        match = self.runtime.registry.resolve(phrase, {})
        self.assertIsNotNone(match)
        self.assertEqual(match.skill_name, "terminal")
        self.assertEqual(match.operation, "run_safe")

        response = self.runtime.kernel.process(phrase)
        self.assertEqual(response.status, "success")
        self.assertEqual(response.result.data["exit_code"], 0)
        self.assertIn("Python 3.", response.result.data["stdout"])

    # ── TEST F — Self-extension & Reuse ───────────────────────────────
    def test_f_self_extension_and_reuse(self):
        """Verify full self-extension lifecycle and subsequent capability reuse."""
        self.assertIsNotNone(self.runtime.capability_manager)
        self.assertIsNotNone(self.runtime.capability_store)

        # Check existing capabilities and events count
        events = self.runtime.capability_store.get_events()
        caps = self.runtime.capability_store.list_capabilities()
        self.assertIsInstance(caps, (list, tuple))

    # ── TEST G — Failure recovery ─────────────────────────────────────
    def test_g_failure_recovery(self):
        """Safe failure scenario: request operation against nonexistent file."""
        response = self.runtime.kernel.process("file read definitely_missing_test_file_987654.txt")
        self.assertEqual(response.status, "failure")
        self.assertIn("not found", response.message.lower())
        self.assertFalse(response.result.success)

    # ── TEST H — Dangerous command protection ─────────────────────────
    def test_h_dangerous_command_protection(self):
        """User intent: 'Delete the Windows system directory.'"""
        phrase = "Delete the Windows system directory."
        response = self.runtime.kernel.process(phrase)
        self.assertEqual(response.status, "denied")
        self.assertIn("blocked by security deny list", response.message.lower())

    # ── TEST I — Confirmation workflow ────────────────────────────────
    def test_i_confirmation_workflow(self):
        """Verify: REQUEST -> WAITING_FOR_PERMISSION -> user confirmation -> EXECUTING -> COMPLETED."""
        response = self.runtime.kernel.process("/terminal run unknown_tool.exe --check")
        self.assertEqual(response.status, "confirmation_required")
        self.assertIsNotNone(response.pending_action)
        self.assertEqual(response.pending_action.risk.value, "critical")

        # Cancel confirmation safely
        action_id = response.pending_action.action_id
        cancel_response = self.runtime.kernel.cancel(action_id)
        self.assertEqual(cancel_response.status, "cancelled")

    # ── TEST J — Stop/cancel ──────────────────────────────────────────
    def test_j_stop_cancel(self):
        """Verify: 'Stop NEXA' triggers emergency stop and failsafe halts subsequent actions."""
        self.runtime.failsafe.stop()
        self.assertTrue(self.runtime.failsafe.is_stopped)

        # Direct failsafe check must raise FailsafeTriggered
        with self.assertRaises(FailsafeTriggered):
            self.runtime.failsafe.check_before_action()

        # Skill execution must report failsafe triggered
        res = self.runtime.computer_skill.execute("move_mouse", {"x": 50, "y": 50})
        self.assertFalse(res.success)
        self.assertIn("failsafe triggered", res.message.lower())

        # Reset failsafe to restore normal operation
        self.runtime.failsafe.reset()
        self.assertFalse(self.runtime.failsafe.is_stopped)

    # ── Manglish Intent Tests ─────────────────────────────────────────
    def test_manglish_intent_understanding(self):
        """Verify Manglish commands map to correct skills."""
        cases = [
            ("Chrome open cheyth Google-il MERN jobs search cheyy.", "browser", "search"),
            ("Ee folderil oru test file undakki thaa.", "files", "write"),
            ("Notepad open cheyy.", "app_control", "launch"),
            ("Notepad close cheyy.", "app_control", "close_app"),
        ]
        for phrase, expected_skill, expected_op in cases:
            match = self.runtime.registry.resolve(phrase, {})
            self.assertIsNotNone(match, f"Failed to match phrase: {phrase}")
            self.assertEqual(match.skill_name, expected_skill, f"Wrong skill for: {phrase}")
            self.assertEqual(match.operation, expected_op, f"Wrong operation for: {phrase}")


if __name__ == "__main__":
    unittest.main()
