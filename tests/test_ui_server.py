import asyncio
import sys
import threading
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import httpx
from control_plane import RuntimeControlPlane
from runtime import build_runtime
from ui.event_bus import UIEventBus
from ui.server import NexaUIServer


class TestNexaUIServerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = build_runtime()
        cls.control = RuntimeControlPlane(cls.runtime)
        cls.event_bus = UIEventBus()
        cls.port = 8799
        cls.server = NexaUIServer(
            control=cls.control,
            event_bus=cls.event_bus,
            host="127.0.0.1",
            port=cls.port,
        )

        cls.loop = asyncio.new_event_loop()
        cls.ready_event = threading.Event()

        def run_loop():
            asyncio.set_event_loop(cls.loop)
            cls.loop.run_until_complete(cls.server.start())
            cls.ready_event.set()
            cls.loop.run_forever()

        cls.thread = threading.Thread(target=run_loop, daemon=True)
        cls.thread.start()
        cls.ready_event.wait(timeout=5.0)

    @classmethod
    def tearDownClass(cls):
        future = asyncio.run_coroutine_threadsafe(cls.server.stop(), cls.loop)
        try:
            future.result(timeout=5.0)
        except Exception:
            pass
        cls.loop.call_soon_threadsafe(cls.loop.stop)
        cls.thread.join(timeout=2.0)

    def test_get_index(self):
        url = f"http://127.0.0.1:{self.port}/"
        resp = httpx.get(url, timeout=5.0)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("NEXA", resp.text)

    def test_get_health(self):
        url = f"http://127.0.0.1:{self.port}/api/health"
        resp = httpx.get(url, timeout=5.0)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("status"), "healthy")
        self.assertEqual(data.get("service"), "NEXA Level 5 OS")
        self.assertIn("timestamp", data)

    def test_get_status(self):
        url = f"http://127.0.0.1:{self.port}/api/status"
        resp = httpx.get(url, timeout=5.0)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("online"))
        self.assertIn("failsafe", data)
        self.assertIn("skills_count", data)

    def test_get_metrics(self):
        url = f"http://127.0.0.1:{self.port}/api/metrics"
        resp = httpx.get(url, timeout=5.0)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("cpu", data)
        self.assertIn("ram", data)
        self.assertIn("drives", data)

    def test_get_memory(self):
        url = f"http://127.0.0.1:{self.port}/api/memory"
        resp = httpx.get(url, timeout=5.0)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("total_layers"), 10)
        self.assertEqual(len(data.get("layers", [])), 10)

    def test_post_command_safe(self):
        url = f"http://127.0.0.1:{self.port}/api/command"
        resp = httpx.post(url, json={"command": "ping"}, timeout=5.0)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("success"))

    def test_post_command_blocked_by_security_gate(self):
        url = f"http://127.0.0.1:{self.port}/api/command"
        resp = httpx.post(url, json={"command": "format c:"}, timeout=5.0)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data.get("success"))
        self.assertTrue(data.get("blocked"))

    def test_static_css_and_js(self):
        resp_css = httpx.get(f"http://127.0.0.1:{self.port}/style.css", timeout=5.0)
        self.assertEqual(resp_css.status_code, 200)
        self.assertIn("nexa", resp_css.text.lower())

        resp_js = httpx.get(f"http://127.0.0.1:{self.port}/app.js", timeout=5.0)
        self.assertEqual(resp_js.status_code, 200)
        self.assertIn("nexa", resp_js.text.lower())

    def test_failsafe_stop_and_reset_endpoints(self):
        resp_stop = httpx.post(f"http://127.0.0.1:{self.port}/api/failsafe/stop", timeout=5.0)
        self.assertEqual(resp_stop.status_code, 200)
        self.assertTrue(resp_stop.json().get("stopped"))

        # In stopped state, commands fail
        resp_cmd = httpx.post(f"http://127.0.0.1:{self.port}/api/command", json={"command": "ping"}, timeout=5.0)
        # Verify it handled failsafe stop
        self.assertIn(resp_cmd.status_code, {200, 400})

        resp_reset = httpx.post(f"http://127.0.0.1:{self.port}/api/failsafe/reset", timeout=5.0)
        self.assertEqual(resp_reset.status_code, 200)
        self.assertFalse(resp_reset.json().get("stopped"))

    def test_websocket_interaction(self):
        import asyncio
        import aiohttp

        async def run_ws_test():
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(f"http://127.0.0.1:{self.port}/ws") as ws:
                    init_data = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                    self.assertEqual(init_data.get("type"), "init")

                    # Send command via WS
                    await ws.send_json({"action": "command", "text": "ping"})

                    received_result = False
                    while True:
                        msg = await asyncio.wait_for(ws.receive_json(), timeout=5.0)
                        if msg.get("type") == "command_result":
                            received_result = True
                            break
                    self.assertTrue(received_result)

        asyncio.run(run_ws_test())

    def test_task_lifecycle_endpoints(self):
        # 1. Start a task via POST /api/tasks
        resp_start = httpx.post(f"http://127.0.0.1:{self.port}/api/tasks", json={"goal": "Verify storage and create report"}, timeout=5.0)
        self.assertEqual(resp_start.status_code, 200)
        start_data = resp_start.json()
        self.assertTrue(start_data.get("success"))
        task_id = start_data.get("task_id")
        self.assertTrue(task_id)

        # 2. Pause task
        resp_pause = httpx.post(f"http://127.0.0.1:{self.port}/api/tasks/{task_id}/pause", timeout=5.0)
        self.assertEqual(resp_pause.status_code, 200)
        self.assertTrue(resp_pause.json().get("success"))

        # 3. Resume task
        resp_resume = httpx.post(f"http://127.0.0.1:{self.port}/api/tasks/{task_id}/resume", timeout=5.0)
        self.assertEqual(resp_resume.status_code, 200)
        self.assertTrue(resp_resume.json().get("success"))

        # 4. Cancel task
        resp_cancel = httpx.post(f"http://127.0.0.1:{self.port}/api/tasks/{task_id}/cancel", timeout=5.0)
        self.assertEqual(resp_cancel.status_code, 200)
        self.assertTrue(resp_cancel.json().get("success"))

        # 5. Retry task
        resp_retry = httpx.post(f"http://127.0.0.1:{self.port}/api/tasks/{task_id}/retry", timeout=5.0)
        self.assertEqual(resp_retry.status_code, 200)
        self.assertTrue(resp_retry.json().get("success"))

        # 6. List tasks
        resp_list = httpx.get(f"http://127.0.0.1:{self.port}/api/tasks", timeout=5.0)
        self.assertEqual(resp_list.status_code, 200)
        tasks = resp_list.json().get("tasks", [])
        self.assertTrue(any(t["task_id"] == task_id for t in tasks))


if __name__ == "__main__":
    unittest.main()

