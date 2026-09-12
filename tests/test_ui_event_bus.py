import asyncio
import sys
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.event_bus import UIEvent, UIEventBus, UIEventType, get_event_bus, sanitize_event_data


class TestUIEventBus(unittest.TestCase):
    def setUp(self):
        self.bus = UIEventBus()

    def test_sanitize_event_data_redacts_secrets(self):
        data = {
            "normal_field": "public info",
            "password": "super_secret_password",
            "token": "ghp_1234567890abcdef",
            "api_key": "AIzaSyD-123456789",
            "nested": {
                "auth_header": "Bearer abcdef1234567890",
                "otp": "987654",
                "safe_nested": 42,
            },
            "list_field": [
                {"cookie": "session=secret123"},
                "safe_item",
            ],
            "raw_text": "Authorization: Bearer 9876543210fedcba in message",
        }

        sanitized = sanitize_event_data(data)

        self.assertEqual(sanitized["normal_field"], "public info")
        self.assertEqual(sanitized["password"], "[REDACTED]")
        self.assertEqual(sanitized["token"], "[REDACTED]")
        self.assertEqual(sanitized["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["auth_header"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["otp"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["safe_nested"], 42)
        self.assertEqual(sanitized["list_field"][0]["cookie"], "[REDACTED]")
        self.assertEqual(sanitized["list_field"][1], "safe_item")
        self.assertIn("Bearer [REDACTED]", sanitized["raw_text"])

    def test_emit_and_subscribe_sync(self):
        received = []

        def callback(evt: UIEvent):
            received.append(evt)

        self.bus.subscribe(callback)

        event = self.bus.emit(
            UIEventType.TASK_STARTED,
            "Storage Audit",
            "Scanning C: and D: drives",
            {"drives": ["C:", "D:"], "password": "do_not_leak"},
        )

        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].event_type, UIEventType.TASK_STARTED)
        self.assertEqual(received[0].title, "Storage Audit")
        self.assertEqual(received[0].data["drives"], ["C:", "D:"])
        self.assertEqual(received[0].data["password"], "[REDACTED]")

        # Test unsubscribe
        self.bus.unsubscribe(callback)
        self.bus.emit(UIEventType.TASK_COMPLETED, "Done")
        self.assertEqual(len(received), 1)

    def test_async_queue_subscriber(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_async_test():
            queue = self.bus.register_async_queue()

            self.bus.emit(UIEventType.CONFIRMATION_REQUIRED, "Confirm delete", "Details here")

            evt = await asyncio.wait_for(queue.get(), timeout=1.0)
            self.assertEqual(evt.event_type, UIEventType.CONFIRMATION_REQUIRED)
            self.assertEqual(evt.title, "Confirm delete")

            self.bus.unregister_async_queue(queue)

        try:
            loop.run_until_complete(run_async_test())
        finally:
            loop.close()

    def test_recent_events_and_filtering(self):
        self.bus.clear_history()
        self.bus.emit(UIEventType.TASK_STARTED, "T1", task_id="task_1")
        self.bus.emit(UIEventType.TASK_PROGRESS, "P1", task_id="task_1")
        self.bus.emit(UIEventType.TASK_STARTED, "T2", task_id="task_2")

        recent = self.bus.get_recent_events(limit=10)
        self.assertEqual(len(recent), 3)

        t1_events = self.bus.get_recent_events(task_id="task_1")
        self.assertEqual(len(t1_events), 2)

        started_events = self.bus.get_recent_events(event_type=UIEventType.TASK_STARTED)
        self.assertEqual(len(started_events), 2)


if __name__ == "__main__":
    unittest.main()
