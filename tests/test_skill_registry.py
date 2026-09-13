import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import SkillRegistry
from skill_registry import handle_skill_command, is_skill_list_request, render_skill_list
from skills.dummy_skill import DummySkill


class SkillRegistryTests(unittest.TestCase):
    def test_detects_manglish_skill_list_request(self):
        self.assertTrue(is_skill_list_request("ninte skils list cheythe"))
        self.assertTrue(is_skill_list_request("ninte skills list cheyyu"))

    def test_unrelated_chat_is_not_skill_request(self):
        self.assertFalse(is_skill_list_request("python padippikku"))

    def test_registry_lists_runtime_plugins_plus_real_builtin_services(self):
        registry = SkillRegistry()
        registry.register(DummySkill())
        text = render_skill_list(registry)
        self.assertIn("Personal Memory", text)
        self.assertIn("Teacher-Student Language Layer", text)
        self.assertIn("dummy", text)
        self.assertNotIn("Git Operator v1", text)
        self.assertNotIn("Docker", text)
        self.assertNotIn("Cloud Computing", text)

    def test_handler_returns_deterministic_runtime_registry(self):
        registry = SkillRegistry()
        registry.register(DummySkill())
        reply = handle_skill_command("/skills", registry)
        self.assertIsNotNone(reply)
        self.assertIn("installed/active capabilities", reply)
        self.assertIn("dummy", reply)


if __name__ == "__main__":
    unittest.main()
