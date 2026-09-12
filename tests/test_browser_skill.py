import sys
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from browser.contracts import BrowserActionResult, PageInfo
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
        self.assertIn("inspect_dom", operations)
        self.assertEqual(operations["inspect_dom"].risk, RiskTier.READ)
        self.assertIn("fill_form", operations)
        self.assertEqual(operations["fill_form"].risk, RiskTier.REMOTE)
        self.assertIn("submit_form", operations)
        self.assertEqual(operations["submit_form"].risk, RiskTier.REMOTE)
        self.assertIn("press_key", operations)
        self.assertEqual(operations["press_key"].risk, RiskTier.REMOTE)
        self.assertIn("wait_for_selector", operations)
        self.assertEqual(operations["wait_for_selector"].risk, RiskTier.READ)
        self.assertIn("scroll", operations)
        self.assertEqual(operations["scroll"].risk, RiskTier.MUTATE)

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

    def test_match_new_operations(self):
        m = self.skill.match("inspect dom", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "inspect_dom")

        m = self.skill.match("extract links", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "extract_links")

        m = self.skill.match("press key Enter", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "press_key")
        self.assertEqual(m.params["key"], "Enter")

        m = self.skill.match("press escape", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "press_key")
        self.assertEqual(m.params["key"], "escape")

        m = self.skill.match("fill username with admin123", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "fill_form")
        self.assertEqual(m.params["field"], "username")
        self.assertEqual(m.params["value"], "admin123")

        m = self.skill.match("submit form", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "submit_form")

        m = self.skill.match("wait for selector #login-btn", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "wait_for_selector")
        self.assertEqual(m.params["selector"], "#login-btn")

        m = self.skill.match("scroll down", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "scroll")
        self.assertEqual(m.params["direction"], "down")

        m = self.skill.match("go back", {})
        self.assertIsNotNone(m)
        self.assertEqual(m.operation, "back")

    def test_validate_open_valid_url(self):
        params = self.skill.validate("open", {"url": "https://google.com"}, {})
        self.assertEqual(params["url"], "https://google.com")
        
        with self.assertRaises(ValueError):
            self.skill.validate("open", {"url": "   "}, {})

    def test_validate_new_operations(self):
        p = self.skill.validate("fill_form", {"field": "search", "value": "test"}, {})
        self.assertEqual(p["fields"], {"search": "test"})

        p = self.skill.validate("press_key", {"key": "Enter"}, {})
        self.assertEqual(p["key"], "Enter")

        p = self.skill.validate("wait_for_selector", {"selector": "#box", "timeout_ms": 3000}, {})
        self.assertEqual(p["selector"], "#box")
        self.assertEqual(p["timeout_ms"], 3000)

        p = self.skill.validate("scroll", {"direction": "down", "amount": 300}, {})
        self.assertEqual(p["direction"], "down")
        self.assertEqual(p["amount"], 300)

    def test_execute_launch_no_playwright(self):
        # We temporarily mock HAS_PLAYWRIGHT to False just for this test
        import browser.engine
        original_has = browser.engine.HAS_PLAYWRIGHT
        browser.engine.HAS_PLAYWRIGHT = False
        
        try:
            skill = BrowserSkill()
            result = skill.execute("launch", {}, {})
            self.assertFalse(result.success)
            self.assertIn("Playwright", result.error)
            # Verify structured result format
            self.assertIn("success", result.data)
            self.assertIn("action", result.data)
            self.assertIn("target", result.data)
            self.assertIn("observation", result.data)
            self.assertIn("error", result.data)
            self.assertIn("screenshot", result.data)
            self.assertIn("metadata", result.data)
        finally:
            browser.engine.HAS_PLAYWRIGHT = original_has

    def test_structured_return_contract_on_mock_engine(self):
        mock_engine = MagicMock()
        mock_engine.is_launched = True
        mock_engine.launch.return_value = BrowserActionResult(
            success=True,
            action="launch",
            target="chromium",
            observation={"browser_type": "chromium"},
            message="Browser launched.",
        )
        mock_engine.inspect_dom.return_value = {
            "title": "Test Page",
            "url": "https://example.org",
            "buttons": [{"text": "Submit", "selector": "button"}],
            "inputs": [{"name": "q", "selector": "input[name='q']"}],
            "links": [{"text": "Home", "url": "https://example.org"}],
            "forms": [{"id": "form1"}],
            "total_interactive": 3,
        }
        mock_engine.fill_form.return_value = BrowserActionResult(
            success=True,
            action="fill_form",
            target="['username']",
            observation={"filled": ["username"], "errors": []},
            message="Filled form fields: username",
        )
        mock_engine.current_page.return_value = PageInfo(
            url="https://example.org",
            title="Test Page",
            status_code=200,
            is_loaded=True,
        )

        skill = BrowserSkill(engine=mock_engine)

        # 1. Test inspect_dom
        res = skill.execute("inspect_dom", {}, {})
        self.assertTrue(res.success)
        self.assertEqual(res.data["action"], "inspect_dom")
        self.assertIn("observation", res.data)
        self.assertEqual(res.data["observation"]["total_interactive"], 3)
        self.assertIn("success", res.data)
        self.assertIn("target", res.data)
        self.assertIn("error", res.data)
        self.assertIn("screenshot", res.data)
        self.assertIn("metadata", res.data)

        # 2. Test fill_form
        res = skill.execute("fill_form", {"fields": {"username": "admin"}}, {})
        self.assertTrue(res.success)
        self.assertEqual(res.data["action"], "fill_form")
        self.assertEqual(res.data["observation"]["filled"], ["username"])

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
