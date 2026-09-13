from __future__ import annotations

import base64
import http.server
import socketserver
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from skills.browser_control_skill import BrowserControlSkill, BrowserOperationResult
from browser.browsercontrol_adapter import BrowserControlAdapter, ObservationResult

TEST_HTML = """<!DOCTYPE html>
<html>
<head><title>NEXA Deterministic Browser Test</title></head>
<body>
  <h1>Deterministic Test Page</h1>
  <form id="test-form" onsubmit="event.preventDefault(); document.getElementById('result').innerText = 'Submitted: ' + document.getElementById('test-input').value;">
    <input type="text" id="test-input" placeholder="Type here..." />
    <button type="submit" id="submit-btn">Submit Action</button>
  </form>
  <div id="result">Initial State</div>
  <a id="test-link" href="/page2">Go to Page 2</a>
</body>
</html>
"""

PAGE2_HTML = """<!DOCTYPE html>
<html>
<head><title>Page 2</title></head>
<body>
  <h1>Welcome to Page 2</h1>
  <div id="page2-content">Second Page Loaded</div>
</body>
</html>
"""


class DeterministicHttpHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/test.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(TEST_HTML.encode("utf-8"))
        elif self.path == "/page2":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(PAGE2_HTML.encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress console noise


class TestBrowserControlDeterministicSuite(unittest.TestCase):
    """Deterministic 12-step self-test suite for BrowserControlSkill."""

    @classmethod
    def setUpClass(cls):
        # Start local deterministic HTTP test server on an ephemeral port
        cls.server = socketserver.TCPServer(("127.0.0.1", 0), DeterministicHttpHandler)
        cls.port = cls.server.server_address[1]
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        # Create mock adapter that models a real browser session
        self.mock_adapter = MagicMock(spec=BrowserControlAdapter)
        self.mock_adapter.is_connected = True
        self.dom_state = {
            "title": "NEXA Deterministic Browser Test",
            "url": f"{self.base_url}/test.html",
            "input_val": "",
            "result_text": "Initial State",
            "tabs": [{"targetId": "tab_1", "url": f"{self.base_url}/test.html", "title": "NEXA Test"}],
            "active_tab": "tab_1",
        }

        # Mock adapter evaluate behavior simulating local DOM reactions
        def mock_eval(expr: str):
            if "document.title" in expr and "window.location.href" in expr:
                return {"url": self.dom_state["url"], "title": self.dom_state["title"]}
            if "submit-btn" in expr and "click" in expr:
                self.dom_state["result_text"] = f"Submitted: {self.dom_state['input_val']}"
                return True
            if "result" in expr and "innerText" in expr:
                return self.dom_state["result_text"]
            if "test-input" in expr and "focus" in expr:
                return True
            if "nonexistent-selector" in expr:
                return False
            if "document.querySelector('article, main, body')" in expr:
                return f"Deterministic Test Page\n{self.dom_state['result_text']}"
            if "Boolean(document.querySelector('#submit-btn'))" in expr:
                return True
            return True

        self.mock_adapter.evaluate.side_effect = mock_eval
        self.mock_adapter.observe.return_value = ObservationResult(
            observation_id="obs_deterministic_1",
            visual_epoch=1,
            viewport_width=1280,
            viewport_height=800,
            image_width=1280,
            image_height=800,
            screenshot_bytes=b"\x89PNG\r\n\x1a\nfake_screenshot",
        )
        self.mock_adapter.tabs.return_value = self.dom_state["tabs"]
        self.mock_adapter.new_tab.return_value = {"targetId": "tab_2", "url": "about:blank"}

        def mock_type(obs_id, text):
            self.dom_state["input_val"] += text

        self.mock_adapter.type_text.side_effect = mock_type

        self.skill = BrowserControlSkill(adapter=self.mock_adapter)

    def test_12_step_browser_control_lifecycle(self):
        print("\n--- BEGINNING DETERMINISTIC BROWSER CONTROL SELF-TEST ---")

        # Step 1: Open browser / Launch
        res_launch = self.skill.launch()
        self.assertTrue(res_launch.success, "Step 1 Failed: Browser launch")
        print("  [PASS] Step 1: Open/Launch Browser: PASS")

        # Step 2: Open a known test page
        test_page_url = f"{self.base_url}/test.html"
        res_open = self.skill.open(test_page_url)
        self.assertTrue(res_open.success, "Step 2 Failed: Open test page")
        self.assertEqual(res_open.url, test_page_url)
        print("  [PASS] Step 2: Open known test page: PASS")

        # Step 3: Find an element (Wait for / inspect)
        res_wait = self.skill.wait_for("#submit-btn", timeout_ms=1000)
        self.assertTrue(res_wait.success, "Step 3 Failed: Find element")
        print("  [PASS] Step 3: Find element (#submit-btn): PASS")

        # Step 4: Type text into input
        res_type = self.skill.type("#test-input", "Autonomous Level 5 Engine")
        self.assertTrue(res_type.success, "Step 4 Failed: Type text")
        self.assertEqual(self.dom_state["input_val"], "Autonomous Level 5 Engine")
        print("  [PASS] Step 4: Type text into input: PASS")

        # Step 5: Click submit button
        res_click = self.skill.click("#submit-btn")
        self.assertTrue(res_click.success, "Step 5 Failed: Click submit")
        print("  [PASS] Step 5: Click submit button: PASS")

        # Step 6: Verify DOM updated from submission
        self.assertEqual(self.dom_state["result_text"], "Submitted: Autonomous Level 5 Engine")
        print("  [PASS] Step 6: Form submitted and state mutated: PASS")

        # Step 7: Read resulting page
        res_extract = self.skill.extract()
        self.assertTrue(res_extract.success, "Step 7 Failed: Read resulting page")
        self.assertIn("Autonomous Level 5 Engine", res_extract.result.get("text", ""))
        print("  [PASS] Step 7: Read resulting page content: PASS")

        # Step 8: Take screenshot
        res_shot = self.skill.screenshot()
        self.assertTrue(res_shot.success, "Step 8 Failed: Screenshot")
        self.assertIsNotNone(res_shot.screenshot)
        print("  [PASS] Step 8: Take screenshot: PASS")

        # Step 9: Open another tab
        res_new_tab = self.skill.new_tab("about:blank")
        self.assertTrue(res_new_tab.success, "Step 9 Failed: Open new tab")
        self.assertEqual(res_new_tab.result.get("targetId"), "tab_2")
        print("  [PASS] Step 9: Open another tab: PASS")

        # Step 10: Switch tabs
        res_switch = self.skill.switch_tab("tab_1")
        self.assertTrue(res_switch.success, "Step 10 Failed: Switch tabs")
        print("  [PASS] Step 10: Switch tabs: PASS")

        # Step 11: Navigate back
        res_back = self.skill.back()
        self.assertTrue(res_back.success, "Step 11 Failed: Navigate back")
        print("  [PASS] Step 11: Navigate back: PASS")

        # Step 12: Recover from a failed selector
        res_fail_sel = self.skill.click("#nonexistent-selector")
        self.assertFalse(res_fail_sel.success)
        self.assertTrue(res_fail_sel.recovery_possible)
        self.assertIn("not found", res_fail_sel.error.lower())
        print("  [PASS] Step 12: Graceful error recovery from failed selector: PASS")

        print("---------------------------------------------------------")
        print("BROWSER CONTROL:")
        print("PASS")
        print("---------------------------------------------------------")


if __name__ == "__main__":
    unittest.main()
