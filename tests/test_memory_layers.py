from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.memory_layers import (
    ApplicationContext,
    BrowserContext,
    CapabilityMemory,
    ConversationMemory,
    DeviceContext,
    TaskMemory,
    UnifiedMemory,
    UserPreferenceMemory,
)


class MemoryLayersTests(unittest.TestCase):
    def test_conversation_memory(self):
        cm = ConversationMemory(max_turns=3)
        cm.add_turn("user", "Hello")
        cm.add_turn("assistant", "Hi there!")
        cm.add_turn("user", "What is my next step?")
        cm.add_turn("assistant", "Check email.")

        history = cm.get_history()
        self.assertEqual(len(history), 3)  # capped at max_turns=3
        self.assertEqual(history[-1]["content"], "Check email.")
        self.assertEqual(history[-1]["role"], "assistant")

        cm.clear()
        self.assertEqual(len(cm.get_history()), 0)

    def test_user_preference_memory(self):
        upm = UserPreferenceMemory({"default_browser": "chrome"})
        self.assertEqual(upm.get_preference("default_browser"), "chrome")
        self.assertIsNone(upm.get_preference("theme"))

        upm.set_preference("theme", "dark")
        self.assertEqual(upm.get_preference("theme"), "dark")

        prefs = upm.list_preferences()
        self.assertEqual(prefs["default_browser"], "chrome")
        self.assertEqual(prefs["theme"], "dark")

        upm.delete_preference("theme")
        self.assertNotIn("theme", upm.list_preferences())

    def test_task_memory(self):
        tm = TaskMemory()
        self.assertIsNone(tm.get_active_task())

        task = tm.start_task("task_001", "Organize Downloads folder", ["Scan files", "Move images"])
        self.assertEqual(task.current_subgoal, "Scan files")

        tm.record_step("Scanned 15 files", status="completed", result={"count": 15})
        tm.update_subgoal("Move images")

        active = tm.get_active_task()
        self.assertIsNotNone(active)
        self.assertEqual(active["current_subgoal"], "Move images")
        self.assertEqual(len(active["steps"]), 1)

        completed = tm.complete_task(status="success")
        self.assertEqual(completed.status, "success")
        self.assertIsNone(tm.get_active_task())
        self.assertEqual(len(tm.get_task_history()), 1)

    def test_capability_memory(self):
        cap_mem = CapabilityMemory()
        cap_mem.record_usage("browser_search", success=True)
        cap_mem.record_usage("browser_search", success=True)
        cap_mem.record_usage("browser_search", success=False)

        summary = cap_mem.get_usage_summary()
        self.assertEqual(summary["browser_search"]["success"], 2)
        self.assertEqual(summary["browser_search"]["failure"], 1)

        cap_mem.record_gap("Extract RAR file", "rar_extract")
        gaps = cap_mem.get_unresolved_gaps()
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["gap"], "rar_extract")

    def test_application_context(self):
        app_ctx = ApplicationContext()
        app_ctx.set_active_window("Visual Studio Code", "code.exe", 1024)
        win = app_ctx.get_active_window()
        self.assertEqual(win["title"], "Visual Studio Code")
        self.assertEqual(win["process_name"], "code.exe")
        self.assertEqual(win["handle"], 1024)

        app_ctx.set_running_apps(["code.exe", "chrome.exe", "powershell.exe"])
        self.assertIn("chrome.exe", app_ctx.get_running_apps())

    def test_browser_context_search_continuation(self):
        bc = BrowserContext()
        bc.set_current_page("https://google.com", "Google Search")
        self.assertEqual(bc.get_current_page()["url"], "https://google.com")

        # Record mock search results
        results = [
            {"title": "FastAPI Framework", "url": "https://fastapi.tiangolo.com"},
            {"title": "Flask Documentation", "url": "https://flask.palletsprojects.com"},
            {"title": "Django Project", "url": "https://djangoproject.com"},
        ]
        bc.record_search_results(results)

        # 1. "open the second one" -> Flask
        match2 = bc.resolve_search_continuation("open the second one")
        self.assertIsNotNone(match2)
        self.assertEqual(match2["url"], "https://fastapi.tiangolo.com" if False else "https://flask.palletsprojects.com")
        self.assertEqual(match2["index"], 1)

        # 2. "click the 1st link" -> FastAPI
        match1 = bc.resolve_search_continuation("click the 1st link")
        self.assertIsNotNone(match1)
        self.assertEqual(match1["url"], "https://fastapi.tiangolo.com")
        self.assertEqual(match1["index"], 0)

        # 3. "result 3" -> Django
        match3 = bc.resolve_search_continuation("result 3")
        self.assertIsNotNone(match3)
        self.assertEqual(match3["url"], "https://djangoproject.com")
        self.assertEqual(match3["index"], 2)

        # 4. "open the last one" -> Django
        match_last = bc.resolve_search_continuation("open the last one")
        self.assertIsNotNone(match_last)
        self.assertEqual(match_last["url"], "https://djangoproject.com")
        self.assertEqual(match_last["index"], 2)

        # 5. Out of bounds or unrelated
        self.assertIsNone(bc.resolve_search_continuation("open the 10th one"))
        self.assertIsNone(bc.resolve_search_continuation("something completely unrelated"))

    def test_device_context(self):
        dc = DeviceContext(1920, 1080, 1.0, "Windows 11", 1)
        info = dc.get_device_info()
        self.assertEqual(info["screen_width"], 1920)
        self.assertEqual(info["screen_height"], 1080)
        self.assertEqual(info["dpi_scale"], 1.0)
        self.assertEqual(info["os_info"], "Windows 11")

        dc.update_resolution(2560, 1440, 1.25)
        info2 = dc.get_device_info()
        self.assertEqual(info2["screen_width"], 2560)
        self.assertEqual(info2["dpi_scale"], 1.25)

    def test_unified_memory(self):
        um = UnifiedMemory()
        um.conversation.add_turn("user", "Show me the weather")
        um.user_preferences.set_preference("temp_unit", "celsius")
        um.task.start_task("t1", "Check weather")
        um.application.set_active_window("WeatherApp", "weather.exe")
        um.browser.set_current_page("https://weather.com", "Weather")
        um.browser.record_search_results(["result A", "result B"])

        snap = um.snapshot()
        self.assertIn("conversation_history", snap)
        self.assertEqual(snap["user_preferences"]["temp_unit"], "celsius")
        self.assertEqual(snap["active_task"]["task_id"], "t1")
        self.assertEqual(snap["search_results_count"], 2)
        self.assertEqual(snap["device_info"]["screen_width"], 1920)


if __name__ == "__main__":
    unittest.main()
