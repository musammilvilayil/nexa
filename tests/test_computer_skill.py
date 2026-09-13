from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.contracts import RiskTier, ExecutionResult
from core.failsafe import FailsafeMonitor, FailsafeTriggered, FailsafeReason
from skills.computer_skill import ComputerSkill


class MockWindowManager:
    def list_windows(self) -> list[str]:
        return ["Window 1", "Window 2"]
    def focus_window(self, title: str) -> bool:
        return True


class MockFailsafe(FailsafeMonitor):
    def check_before_action(self, *, mouse_x: int | None = None, mouse_y: int | None = None) -> None:
        raise FailsafeTriggered(FailsafeReason.MANUAL_STOP, "Mock failsafe triggered")


class TestComputerSkill(unittest.TestCase):
    def setUp(self):
        self.skill = ComputerSkill()

    def test_metadata_operations(self):
        meta = self.skill.metadata
        self.assertEqual(meta.name, "computer")
        ops_dict = {op.name: op for op in meta.operations}
        self.assertEqual(len(ops_dict), 11)
        
        expected_tiers = {
            "screenshot": RiskTier.READ,
            "find_element": RiskTier.READ,
            "window_list": RiskTier.READ,
            "window_focus": RiskTier.MUTATE,
            "clipboard_get": RiskTier.READ,
            "clipboard_set": RiskTier.MUTATE,
            "move_mouse": RiskTier.MUTATE,
            "click": RiskTier.CRITICAL,
            "type_text": RiskTier.CRITICAL,
            "hotkey": RiskTier.CRITICAL,
            "scroll": RiskTier.MUTATE,
        }
        for op, tier in expected_tiers.items():
            self.assertIn(op, ops_dict)
            self.assertEqual(ops_dict[op].risk, tier)

    def test_match_screenshot(self):
        match = self.skill.match("take a screenshot")
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "screenshot")

    def test_match_click(self):
        match = self.skill.match("click at 100, 200")
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "click")
        self.assertEqual(match.params["x"], 100)
        self.assertEqual(match.params["y"], 200)

    def test_match_type(self):
        match = self.skill.match('type "hello world"')
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "type_text")
        self.assertEqual(match.params["text"], "hello world")

    def test_match_hotkey(self):
        match = self.skill.match("press ctrl+s")
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "hotkey")
        self.assertEqual(match.params["keys"], "ctrl+s")

    def test_match_window_list(self):
        match = self.skill.match("list windows")
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "window_list")

    def test_match_no_match(self):
        match = self.skill.match("random text")
        self.assertIsNone(match)

    def test_validate_click_valid_coords(self):
        # Should not raise exception
        self.skill.validate("click", {"x": 100, "y": 200})

    def test_validate_click_negative_coords(self):
        with self.assertRaises(ValueError):
            self.skill.validate("click", {"x": -100, "y": 200})

    def test_execute_screenshot_no_module(self):
        result = self.skill.execute("screenshot", {})
        self.assertFalse(result.success)
        self.assertIn("ScreenCapture module not available", result.error)

    def test_execute_click_failsafe_triggered(self):
        skill = ComputerSkill(failsafe=MockFailsafe())
        result = skill.execute("click", {"x": 100, "y": 200})
        self.assertFalse(result.success)
        self.assertIn("Mock failsafe triggered", result.error)
        self.assertIn("Failsafe triggered", result.message)

    def test_execute_window_list_mock(self):
        skill = ComputerSkill(window_manager=MockWindowManager())
        result = skill.execute("window_list", {})
        self.assertTrue(result.success)
        self.assertEqual(result.data["windows"], ["Window 1", "Window 2"])


if __name__ == '__main__':
    unittest.main()
