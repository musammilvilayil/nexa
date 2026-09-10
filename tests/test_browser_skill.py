import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from browser.engine import BrowserEngine
from browser.navigator import WebNavigator
from skills.browser_skill import BrowserSkill
from core import RiskTier

class TestBrowserSkill(unittest.TestCase):
    def setUp(self):
        self.skill = BrowserSkill()

    def test_metadata(self):
        meta = self.skill.metadata
        self.assertEqual(meta.name, "browser")
        
        operations = {op.name: op for op in meta.operations}
        self.assertIn("open", operations)
        self.assertEqual(operations["open"].risk, RiskTier.REMOTE)
        self.assertIn("search", operations)
        self.assertEqual(operations["search"].risk, RiskTier.REMOTE)
        self.assertIn("extract", operations)
        self.assertEqual(operations["extract"].risk, RiskTier.READ)
        self.assertIn("launch", operations)
        self.assertEqual(operations["launch"].risk, RiskTier.MUTATE)

    def test_match_open_url(self):
        match = self.skill.match("open google.com", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "open")
        self.assertEqual(match.params["url"], "google.com")
        
        match = self.skill.match("go to example.org", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "open")
        self.assertEqual(match.params["url"], "example.org")

    def test_match_search(self):
        match = self.skill.match("search for python jobs", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "search")
        self.assertEqual(match.params["query"], "python jobs")
        
        match = self.skill.match("google search nexa ai", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "search")
        self.assertEqual(match.params["query"], "nexa ai")

    def test_match_launch(self):
        match = self.skill.match("launch browser", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "launch")

    def test_match_extract(self):
        match = self.skill.match("extract text", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "extract")
        
        match = self.skill.match("read page", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "extract")

    def test_match_no_match(self):
        match = self.skill.match("random text", {})
        self.assertIsNone(match)

    def test_validate_open_valid_url(self):
        params = self.skill.validate("open", {"url": "https://google.com"}, {})
        self.assertEqual(params["url"], "https://google.com")
        
        with self.assertRaises(ValueError):
            self.skill.validate("open", {"url": "   "}, {})

    def test_execute_launch_no_playwright(self):
        # We temporarily mock HAS_PLAYWRIGHT to False just for this test
        import browser.engine
        original_has = browser.engine.HAS_PLAYWRIGHT
        browser.engine.HAS_PLAYWRIGHT = False
        
        try:
            # Create a fresh skill to pick up the mock
            skill = BrowserSkill()
            result = skill.execute("launch", {}, {})
            self.assertFalse(result.success)
            self.assertIn("Playwright", result.error)
        finally:
            browser.engine.HAS_PLAYWRIGHT = original_has

    def test_match_manglish(self):
        match = self.skill.match("chrome open cheyy", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "launch")

    def test_match_search_manglish(self):
        match = self.skill.match("google il jobs search cheyy", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "search")
        self.assertEqual(match.params["query"], "jobs")

if __name__ == '__main__':
    unittest.main()
