from __future__ import annotations

import json
import sys
import time
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from remote.lan_server import LANRemoteServer
from core.failsafe import FailsafeMonitor


class TestLANRemoteServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mock_cp = MagicMock()
        cls.mock_cp.execute_pipeline.return_value = {"success": True, "message": "Command executed via LAN"}
        cls.failsafe = FailsafeMonitor()
        # Bind to 127.0.0.1 on ephemeral port for testing
        cls.server = LANRemoteServer(
            host="127.0.0.1",
            port=0,
            control_plane=cls.mock_cp,
            failsafe=cls.failsafe,
            pairing_pin="654321",
        )
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls.server.start_in_thread()
        time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.server.stop_server()

    def test_01_get_mobile_ui(self):
        req = urllib.request.Request(f"{self.base_url}/")
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            html = resp.read().decode("utf-8")
            self.assertIn("NEXA Mobile Remote", html)
            self.assertIn("EMERGENCY STOP", html)

    def test_02_pair_invalid_pin(self):
        req = urllib.request.Request(
            f"{self.base_url}/api/pair",
            data=json.dumps({"pin": "000000"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        try:
            urllib.request.urlopen(req, timeout=3)
            self.fail("Expected 401 Unauthorized")
        except urllib.error.HTTPError as err:
            self.assertEqual(err.code, 401)

    def test_03_pair_valid_pin_and_execute_command(self):
        # 1. Pair
        req = urllib.request.Request(
            f"{self.base_url}/api/pair",
            data=json.dumps({"pin": "654321"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(data["success"])
            token = data["token"]

        # 2. Status
        req_st = urllib.request.Request(
            f"{self.base_url}/api/status",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req_st, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            st_data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(st_data["ok"])

        # 3. Command
        req_cmd = urllib.request.Request(
            f"{self.base_url}/api/command",
            data=json.dumps({"command": "open notepad"}).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req_cmd, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            cmd_data = json.loads(resp.read().decode("utf-8"))
            self.assertTrue(cmd_data["success"])
            self.mock_cp.execute_pipeline.assert_called_with("open notepad", auto_confirm=True)

    def test_04_emergency_stop_via_lan(self):
        token = list(self.server.active_tokens)[0]
        req_stop = urllib.request.Request(
            f"{self.base_url}/api/emergency_stop",
            data=b"{}",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
        )
        with urllib.request.urlopen(req_stop, timeout=3) as resp:
            self.assertEqual(resp.status, 200)
            self.assertTrue(self.failsafe.is_stopped)


if __name__ == "__main__":
    unittest.main()

