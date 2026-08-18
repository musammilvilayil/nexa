import unittest

from src.language import LanguageResult, detect_language


class LanguageDetectionTests(unittest.TestCase):
    def test_detects_malayalam_script(self):
        self.assertEqual(detect_language("സുഖമാണോ?"), "malayalam")

    def test_detects_short_manglish(self):
        self.assertEqual(detect_language("sugam ahno"), "manglish")

    def test_detects_longer_manglish(self):
        self.assertEqual(
            detect_language("nammal ippo entha cheyyande"),
            "manglish",
        )

    def test_detects_english(self):
        self.assertEqual(detect_language("what should we build next"), "english")

    def test_manglish_model_context_preserves_original(self):
        result = LanguageResult(
            original="nammal ippo entha cheyyande",
            detected_language="manglish",
            normalized_malayalam="നമ്മൾ ഇപ്പോൾ എന്താ ചെയ്യേണ്ടത്?",
            meaning_english="What should we do now?",
            confidence=0.95,
            provider="test",
        )

        model_text = result.model_text()
        self.assertIn(result.original, model_text)
        self.assertIn(result.normalized_malayalam, model_text)
        self.assertIn(result.meaning_english, model_text)


if __name__ == "__main__":
    unittest.main()
