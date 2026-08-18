import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from language import LanguageResult
from nexa import _is_translation_echo


class ReplyGuardTests(unittest.TestCase):
    def _result(self):
        return LanguageResult(
            original="njan innu valare tired aanu, kurach neram rest edukkatte?",
            detected_language="manglish",
            normalized_malayalam="ഞാൻ ഇന്ന് വളരെ tired ആണ്, കുറച്ച് നേരം rest എടുക്കട്ടെ?",
            meaning_english="I am very tired today. Should I rest for a while?",
            confidence=1.0,
            provider="teacher:test",
        )

    def test_detects_acknowledgement_plus_copied_question(self):
        reply = "Athe, njan innu valare tired aanu, kurach neram rest edukkatte."
        self.assertTrue(_is_translation_echo(reply, self._result()))

    def test_allows_real_answer(self):
        reply = "Athe, kurach neram rest edukku. Fresh aayittu pinne continue cheyyam."
        self.assertFalse(_is_translation_echo(reply, self._result()))


if __name__ == "__main__":
    unittest.main()
