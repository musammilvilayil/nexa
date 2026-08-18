import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from skill_registry import handle_skill_command, is_skill_list_request, render_skill_list


class SkillRegistryTests(unittest.TestCase):
    def test_detects_manglish_skill_list_request(self):
        self.assertTrue(is_skill_list_request("ninte skils list cheythe"))
        self.assertTrue(is_skill_list_request("ninte skills list cheyyu"))

    def test_unrelated_chat_is_not_skill_request(self):
        self.assertFalse(is_skill_list_request("python padippikku"))

    def test_registry_lists_only_real_current_skills(self):
        text = render_skill_list()
        self.assertIn("Personal Memory", text)
        self.assertIn("Teacher-Student Language Layer", text)
        self.assertIn("Git Operator v1", text)
        self.assertNotIn("Docker", text)
        self.assertNotIn("Cloud Computing", text)

    def test_handler_returns_deterministic_registry(self):
        reply = handle_skill_command("/skills")
        self.assertIsNotNone(reply)
        self.assertIn("installed/active skills", reply)


if __name__ == "__main__":
    unittest.main()
