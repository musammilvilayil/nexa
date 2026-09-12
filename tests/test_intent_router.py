from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.intent_router import IntentRouter, IntentType


class TestIntentRouter(unittest.TestCase):
    def setUp(self):
        self.router = IntentRouter()

    def test_chat_greetings(self):
        res = self.router.classify("hey Alexa how are you")
        self.assertEqual(res.intent_type, IntentType.CHAT)

        res2 = self.router.classify("hello there")
        self.assertEqual(res2.intent_type, IntentType.CHAT)

        res3 = self.router.classify("can you")
        self.assertEqual(res3.intent_type, IntentType.CHAT)

    def test_action_commands(self):
        res = self.router.classify("open calculator")
        self.assertEqual(res.intent_type, IntentType.AGENT_TASK)

        res2 = self.router.classify("open notepad and type hello")
        self.assertEqual(res2.intent_type, IntentType.AGENT_TASK)

        res3 = self.router.classify("type hello world")
        self.assertEqual(res3.intent_type, IntentType.AGENT_TASK)

        res4 = self.router.classify("show system status")
        self.assertEqual(res4.intent_type, IntentType.AGENT_TASK)

    def test_polite_action_command(self):
        res = self.router.classify("can you open notepad")
        self.assertEqual(res.intent_type, IntentType.AGENT_TASK)
        self.assertIn("open notepad", res.action_prompt.lower())

    def test_information_queries(self):
        res = self.router.classify("what is python")
        self.assertEqual(res.intent_type, IntentType.INFORMATION)

        res2 = self.router.classify("explain how quantum computers work")
        self.assertEqual(res2.intent_type, IntentType.INFORMATION)

    def test_mixed_intent(self):
        res = self.router.classify("what is Upwork and open it")
        self.assertEqual(res.intent_type, IntentType.MIXED)
        self.assertTrue(len(res.action_prompt) > 0)
        self.assertTrue(len(res.chat_prompt) > 0)


if __name__ == "__main__":
    unittest.main()
