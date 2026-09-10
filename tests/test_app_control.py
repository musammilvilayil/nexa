import sys
from pathlib import Path

# Add src to python path for testing
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import unittest
from computer.app_control import AppInfo, ApplicationRegistry, ApplicationLauncher
from skills.app_skill import AppSkill
from core.contracts import RiskTier

class TestAppControl(unittest.TestCase):
    def test_app_info_dataclass(self):
        app = AppInfo("TestApp", "test.exe", ("tapp",))
        self.assertEqual(app.name, "TestApp")
        self.assertEqual(app.executable, "test.exe")
        self.assertEqual(app.aliases, ("tapp",))

    def test_registry_defaults(self):
        reg = ApplicationRegistry()
        apps = reg.list_apps()
        names = [a.name for a in apps]
        self.assertIn("Chrome", names)
        self.assertIn("VS Code", names)
        self.assertIn("Notepad", names)

    def test_registry_find_by_name(self):
        reg = ApplicationRegistry()
        app = reg.find("chrome")
        self.assertIsNotNone(app)
        self.assertEqual(app.name, "Chrome")

    def test_registry_find_by_alias(self):
        reg = ApplicationRegistry()
        app = reg.find("vscode")
        self.assertIsNotNone(app)
        self.assertEqual(app.name, "VS Code")

    def test_registry_find_case_insensitive(self):
        reg = ApplicationRegistry()
        app = reg.find("CHROME")
        self.assertIsNotNone(app)
        self.assertEqual(app.name, "Chrome")

    def test_registry_find_not_found(self):
        reg = ApplicationRegistry()
        self.assertIsNone(reg.find("nonexistent"))

    def test_registry_register_custom(self):
        reg = ApplicationRegistry()
        reg.register(AppInfo("CustomApp", "custom.exe", ("capp",)))
        app = reg.find("capp")
        self.assertIsNotNone(app)
        self.assertEqual(app.name, "CustomApp")

    def test_registry_list_apps(self):
        reg = ApplicationRegistry()
        apps = reg.list_apps()
        self.assertTrue(len(apps) > 0)
        # Check sorting
        names = [a.name for a in apps]
        self.assertEqual(names, sorted(names))

    def test_app_skill_metadata(self):
        skill = AppSkill()
        meta = skill.metadata
        self.assertEqual(meta.name, "app_control")
        op_names = {op.name: op.risk for op in meta.operations}
        self.assertEqual(op_names["launch"], RiskTier.MUTATE)
        self.assertEqual(op_names["list_apps"], RiskTier.READ)
        self.assertEqual(op_names["find_app"], RiskTier.READ)
        self.assertEqual(op_names["close_app"], RiskTier.DESTRUCTIVE)

    def test_app_skill_match_open(self):
        skill = AppSkill()
        match = skill.match("open chrome", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "launch")
        self.assertEqual(match.params["app_name"], "chrome")
        self.assertEqual(match.confidence, 0.7)

    def test_app_skill_match_list(self):
        skill = AppSkill()
        match = skill.match("list apps", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "list_apps")

    def test_app_skill_match_manglish(self):
        skill = AppSkill()
        match = skill.match("chrome open cheyy", {})
        self.assertIsNotNone(match)
        self.assertEqual(match.operation, "launch")
        self.assertEqual(match.params["app_name"], "chrome")

    def test_app_skill_no_match(self):
        skill = AppSkill()
        self.assertIsNone(skill.match("some random text", {}))

    def test_launcher_app_not_found(self):
        launcher = ApplicationLauncher()
        res = launcher.launch("nonexistent_app")
        self.assertFalse(res["success"])
        self.assertIn("not found in registry", res["message"])

if __name__ == "__main__":
    unittest.main()
