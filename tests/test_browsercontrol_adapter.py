from __future__ import annotations

import base64
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure src is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from browser.browsercontrol_adapter import (
    BrowserControlAdapter,
    BrowserControlError,
    StaleObservationError,
    CoordinateOutOfBoundsError,
    TargetClosedError,
    DialogBlockingError,
    ObservationResult,
    BrowserActionResult,
)
from core.contracts import PolicyDecision, PolicyOutcome, RiskTier
from core.security import SecurityGate
from core.failsafe import FailsafeMonitor, FailsafeTriggered, FailsafeReason
from core.failures import SecurityBlocked, BrowserNavigationFailure


class TestBrowserControlAdapterUnit(unittest.TestCase):
    """Unit tests for BrowserControlAdapter enforcing security, failsafe, observation contract, and error mapping."""

    def setUp(self):
        self.security_gate = SecurityGate()
        self.failsafe = FailsafeMonitor()
        self.adapter = BrowserControlAdapter(
            security_gate=self.security_gate,
            failsafe=self.failsafe,
            strict_observation=True,
        )

    # 1. URL Security validation
    def test_prohibited_url_schemes_blocked(self):
        with self.assertRaises(SecurityBlocked) as ctx:
            self.adapter._validate_url("file:///C:/Windows/System32/calc.exe")
        self.assertIn("prohibited URL scheme", str(ctx.exception))

        with self.assertRaises(SecurityBlocked) as ctx2:
            self.adapter._validate_url("javascript:alert(1)")
        self.assertIn("prohibited URL scheme", str(ctx2.exception))

        with self.assertRaises(SecurityBlocked) as ctx3:
            self.adapter._validate_url("chrome://settings")
        self.assertIn("prohibited URL scheme", str(ctx3.exception))

    def test_valid_urls_allowed(self):
        self.assertEqual(self.adapter._validate_url("https://google.com"), "https://google.com")
        self.assertEqual(self.adapter._validate_url("http://127.0.0.1:8080"), "http://127.0.0.1:8080")
        self.assertEqual(self.adapter._validate_url("about:blank"), "about:blank")
        self.assertEqual(self.adapter._validate_url("github.com"), "https://github.com")

    # 2. Secret / credential protection
    def test_credential_typing_blocked(self):
        with self.assertRaises(SecurityBlocked) as ctx:
            self.adapter._validate_type_text("My password is supersecret123!")
        self.assertIn("credentials", str(ctx.exception))

        with self.assertRaises(SecurityBlocked) as ctx2:
            self.adapter._validate_type_text("api_key=AIzaSyDxyz123456789")
        self.assertIn("credentials", str(ctx2.exception))

        with self.assertRaises(SecurityBlocked) as ctx3:
            self.adapter._validate_type_text("Bearer abcd1234efgh5678ijkl")
        self.assertIn("credentials", str(ctx3.exception))

        # Safe text should not raise
        self.adapter._validate_type_text("Hello world, search for python")

    # 3. Failsafe integration
    def test_failsafe_prevents_input(self):
        self.failsafe.stop(FailsafeReason.MANUAL_STOP)
        with self.assertRaises(FailsafeTriggered):
            self.adapter._assert_failsafe()

    # 4. Observation Contract (strict token lifecycle)
    def test_action_without_observation_raises_stale_error(self):
        # No observation taken yet
        with self.assertRaises(StaleObservationError) as ctx:
            self.adapter._verify_observation_token("fake_obs_123")
        self.assertIn("No active observation", str(ctx.exception))

    def test_observation_token_lifecycle(self):
        # Manually set current token
        self.adapter._current_observation_id = "obs_1_valid"

        # Matching token passes
        self.adapter._verify_observation_token("obs_1_valid")

        # Mismatched token fails
        with self.assertRaises(StaleObservationError) as ctx:
            self.adapter._verify_observation_token("obs_0_outdated")
        self.assertIn("does not match active token", str(ctx.exception))

        # Invalidation clears token
        self.adapter._invalidate_observation()
        self.assertIsNone(self.adapter.current_observation_id)

        with self.assertRaises(StaleObservationError):
            self.adapter._verify_observation_token("obs_1_valid")

    # 5. Error translation
    def test_error_translation_stale_observation(self):
        with self.assertRaises(StaleObservationError):
            self.adapter._translate_and_raise(
                {"errorCode": "STALE_OBSERVATION", "error": "Epoch changed"},
                "click",
                observation_id="obs_1_stale"
            )

    def test_error_translation_out_of_bounds(self):
        with self.assertRaises(CoordinateOutOfBoundsError):
            self.adapter._translate_and_raise(
                {"errorCode": "OUT_OF_BOUNDS", "error": "X exceeds width"},
                "click",
                x=2500,
                y=500
            )

    def test_error_translation_target_closed(self):
        with self.assertRaises(TargetClosedError):
            self.adapter._translate_and_raise(
                {"errorCode": "TARGET_CLOSED", "error": "Tab was detached"},
                "observe"
            )

    def test_error_translation_dialog_blocking(self):
        with self.assertRaises(DialogBlockingError):
            self.adapter._translate_and_raise(
                {"errorCode": "DIALOG_BLOCKING", "error": "Alert dialog open"},
                "click"
            )

    def test_error_translation_navigation_failure(self):
        with self.assertRaises(BrowserNavigationFailure):
            self.adapter._translate_and_raise(
                {"errorCode": "NAVIGATION_FAILED", "error": "net::ERR_NAME_NOT_RESOLVED"},
                "navigate"
            )


class TestBrowserControlAdapterMockIPC(unittest.TestCase):
    """Tests verify IPC protocol methods using mocked bridge responses."""

    def setUp(self):
        self.adapter = BrowserControlAdapter()
        self.adapter._process = MagicMock()
        self.adapter._connected = True

    def test_observe_decodes_screenshot(self):
        fake_png = b"\x89PNG\r\n\x1a\nfake_image_bytes"
        b64_png = base64.b64encode(fake_png).decode("ascii")

        with patch.object(self.adapter, "_send_request", return_value={
            "success": True,
            "data": {
                "observationId": "obs_1_9999",
                "visualEpoch": 1,
                "viewportWidth": 1280,
                "viewportHeight": 800,
                "imageWidth": 1280,
                "imageHeight": 800,
                "image": b64_png,
            }
        }):
            obs = self.adapter.observe()
            self.assertEqual(obs.observation_id, "obs_1_9999")
            self.assertEqual(obs.visual_epoch, 1)
            self.assertEqual(obs.viewport_width, 1280)
            self.assertEqual(obs.screenshot_bytes, fake_png)
            self.assertEqual(self.adapter.current_observation_id, "obs_1_9999")

    def test_click_invalidates_observation_after_success(self):
        self.adapter._current_observation_id = "obs_1_100"

        with patch.object(self.adapter, "_send_request", return_value={
            "success": True,
            "durationMs": 42.0,
            "data": {"clicked": True},
        }):
            res = self.adapter.click("obs_1_100", 150, 200)
            self.assertTrue(res.success)
            self.assertEqual(res.action, "click")
            # Must be invalidated!
            self.assertIsNone(self.adapter.current_observation_id)


if __name__ == "__main__":
    unittest.main()
