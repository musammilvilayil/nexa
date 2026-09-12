from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from browser.browsercontrol_adapter import BrowserControlAdapter, ObservationResult
from skills.google_search_skill import GoogleSearchSkill
from skills.web_navigation_skill import WebNavigationSkill
from skills.web_research_skill import WebResearchSkill


class TestBrowserHigherLevelSkills(unittest.TestCase):
    def setUp(self):
        self.mock_adapter = MagicMock(spec=BrowserControlAdapter)
        self.mock_adapter.is_connected = True
        self.mock_adapter.observe.return_value = ObservationResult(
            observation_id="obs_1_test",
            visual_epoch=1,
            viewport_width=1280,
            viewport_height=800,
            image_width=1280,
            image_height=800,
            screenshot_bytes=b"fake_png",
        )

    def test_google_search_skill_execution(self):
        skill = GoogleSearchSkill(self.mock_adapter)
        self.mock_adapter.evaluate.return_value = [
            {"title": "Python 3.14 Release Notes", "url": "https://python.org/3.14", "snippet": "New features in 3.14"}
        ]

        # Test match
        match = skill.match("search for Python 3.14 features", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "search")
        self.assertEqual(match.params["query"], "Python 3.14 features")

        # Test execute
        res = skill.execute("search", {"query": "Python 3.14 features"}, {})
        self.assertTrue(res.success)
        self.assertIn("Python 3.14 features", res.message)
        self.assertEqual(len(res.data["results"]), 1)
        self.mock_adapter.navigate.assert_called_once()
        self.mock_adapter.observe.assert_called_once()

    def test_web_navigation_skill_execution(self):
        skill = WebNavigationSkill(self.mock_adapter)
        self.mock_adapter.evaluate.return_value = {
            "title": "GitHub: Let's build from here",
            "url": "https://github.com",
            "readyState": "complete",
        }

        # Test match
        match = skill.match("go to https://github.com", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "navigate")
        self.assertEqual(match.params["url"], "https://github.com")

        # Test execute
        res = skill.execute("navigate", {"url": "https://github.com"}, {})
        self.assertTrue(res.success)
        self.assertIn("GitHub", res.message)
        self.mock_adapter.navigate.assert_called_with("https://github.com")

    def test_web_research_skill_composition(self):
        skill = WebResearchSkill(self.mock_adapter)
        # Mock search results
        skill.search_skill.execute = MagicMock(return_value=MagicMock(
            success=True,
            data={"results": [
                {"title": "Python 3.14 What's New", "url": "https://docs.python.org/3.14", "snippet": "Overview"},
                {"title": "Python 3.14 Peeking Ahead", "url": "https://realpython.com/3.14", "snippet": "Guide"},
            ]}
        ))
        skill.nav_skill.execute = MagicMock(return_value=MagicMock(success=True, data={}))
        self.mock_adapter.evaluate.return_value = "Python 3.14 introduces deferred annotations and enhanced JIT compiler speedups."

        # Test match
        match = skill.match("research about Python 3.14", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "research")

        # Test execute
        res = skill.execute("research", {"topic": "Python 3.14"}, {})
        self.assertTrue(res.success)
        self.assertIn("Research Report: Python 3.14", res.message)
        self.assertIn("deferred annotations", res.message)
        self.assertEqual(len(res.data["citations"]), 2)


if __name__ == "__main__":
    unittest.main()
