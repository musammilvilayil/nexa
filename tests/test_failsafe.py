from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.failsafe import (
    FailsafeConfig,
    FailsafeMonitor,
    FailsafeReason,
    FailsafeState,
    FailsafeTriggered,
)

class TestFailsafe(unittest.TestCase):
    def test_default_config(self):
        monitor = FailsafeMonitor()
        self.assertTrue(monitor.config.corner_enabled)
        self.assertEqual(monitor.config.max_actions_per_second, 10.0)

    def test_check_passes_normally(self):
        monitor = FailsafeMonitor()
        monitor.check_before_action()
        self.assertFalse(monitor.is_stopped)

    def test_corner_trigger(self):
        monitor = FailsafeMonitor()
        with self.assertRaises(FailsafeTriggered) as ctx:
            monitor.check_before_action(mouse_x=0, mouse_y=0)
        self.assertEqual(ctx.exception.reason, FailsafeReason.CORNER_TRIGGER)
        self.assertTrue(monitor.is_stopped)

    def test_corner_trigger_within_threshold(self):
        monitor = FailsafeMonitor(FailsafeConfig(corner_threshold_px=5))
        with self.assertRaises(FailsafeTriggered):
            monitor.check_before_action(mouse_x=3, mouse_y=3)
        self.assertTrue(monitor.is_stopped)

    def test_corner_trigger_outside_threshold(self):
        monitor = FailsafeMonitor(FailsafeConfig(corner_threshold_px=5))
        monitor.check_before_action(mouse_x=10, mouse_y=10)
        self.assertFalse(monitor.is_stopped)

    def test_corner_disabled(self):
        monitor = FailsafeMonitor(FailsafeConfig(corner_enabled=False))
        monitor.check_before_action(mouse_x=0, mouse_y=0)
        self.assertFalse(monitor.is_stopped)

    def test_rate_limit(self):
        monitor = FailsafeMonitor(FailsafeConfig(max_actions_per_second=2.0))
        monitor.check_before_action()
        monitor.check_before_action()
        with self.assertRaises(FailsafeTriggered) as ctx:
            monitor.check_before_action()
        self.assertEqual(ctx.exception.reason, FailsafeReason.RATE_LIMIT)

    def test_manual_stop(self):
        monitor = FailsafeMonitor()
        monitor.stop()
        with self.assertRaises(FailsafeTriggered) as ctx:
            monitor.check_before_action()
        self.assertEqual(ctx.exception.reason, FailsafeReason.MANUAL_STOP)

    def test_reset_clears_stop(self):
        monitor = FailsafeMonitor()
        monitor.stop()
        self.assertTrue(monitor.is_stopped)
        monitor.reset()
        self.assertFalse(monitor.is_stopped)
        monitor.check_before_action()

    def test_blocked_process(self):
        monitor = FailsafeMonitor(FailsafeConfig(blocked_processes=frozenset(["Taskmgr.exe"])))
        with self.assertRaises(FailsafeTriggered) as ctx:
            monitor.check_blocked_process("Taskmgr.exe")
        self.assertEqual(ctx.exception.reason, FailsafeReason.BLOCKED_PROCESS)

    def test_blocked_process_case_insensitive(self):
        monitor = FailsafeMonitor(FailsafeConfig(blocked_processes=frozenset(["taskmgr.exe"])))
        with self.assertRaises(FailsafeTriggered):
            monitor.check_blocked_process("TASKMGR.EXE")

    def test_unblocked_process_passes(self):
        monitor = FailsafeMonitor(FailsafeConfig(blocked_processes=frozenset(["taskmgr.exe"])))
        monitor.check_blocked_process("notepad.exe")
        self.assertFalse(monitor.is_stopped)

    def test_callback_on_trigger(self):
        monitor = FailsafeMonitor()
        called_reason = None
        def cb(reason):
            nonlocal called_reason
            called_reason = reason
            
        monitor.on_trigger(cb)
        monitor.stop(FailsafeReason.MANUAL_STOP)
        self.assertEqual(called_reason, FailsafeReason.MANUAL_STOP)

    def test_stopped_flag(self):
        monitor = FailsafeMonitor()
        self.assertFalse(monitor.is_stopped)
        monitor.stop()
        self.assertTrue(monitor.is_stopped)

    def test_cooldown_after_trigger(self):
        # The cooldown check requires triggered_at to be set without stopped=True.
        # This tests the branch in check_before_action.
        monitor = FailsafeMonitor(FailsafeConfig(cooldown_after_trigger_seconds=0.1))
        monitor._state.triggered_at = time.monotonic()
        
        with self.assertRaises(FailsafeTriggered) as ctx:
            monitor.check_before_action()
        self.assertEqual(ctx.exception.reason, FailsafeReason.MANUAL_STOP)
        self.assertTrue("Cooldown active" in str(ctx.exception))

if __name__ == '__main__':
    unittest.main()
