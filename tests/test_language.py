import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from language import LanguageResult, detect_language, prepare_user_input


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

    def test_detects_next_step_manglish(self):
        self.assertEqual(
            detect_language("nammal ini enth cheyyum"),
            "manglish",
        )

    def test_detects_mixed_build_suggestion_as_manglish(self):
        self.assertEqual(
            detect_language("oru platform build cheythalo"),
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

    @patch("language.get_teacher_example")
    def test_reuses_teacher_lesson_as_local_student_knowledge(self, get_lesson):
        get_lesson.return_value = {
            "detected_language": "manglish",
            "normalized_malayalam": "എന്റെ വീട് എവിടെയാണ്?",
            "meaning_english": "Where is my house?",
            "confidence": 0.96,
            "provider": "gemini:gemini-3.5-flash",
            "lesson": "veedu means house",
            "use_count": 2,
        }

        with patch("language.teacher_available") as teacher_available:
            result = prepare_user_input("ente veedu evida")

        self.assertEqual(result.meaning_english, "Where is my house?")
        self.assertTrue(result.provider.startswith("student:learned:"))
        teacher_available.assert_not_called()

    @patch("language.save_language_cache")
    @patch("language.save_teacher_example")
    @patch("language.normalize_manglish")
    @patch("language.teacher_available", return_value=True)
    @patch("language.get_language_cache", return_value=None)
    @patch("language.get_teacher_example", return_value=None)
    def test_unknown_manglish_can_be_taught_by_gemini(
        self,
        _get_lesson,
        _get_cache,
        _teacher_available,
        normalize_manglish,
        save_teacher_example,
        save_language_cache,
    ):
        normalize_manglish.return_value = {
            "normalized_malayalam": "എന്റെ വീട് എവിടെയാണ്?",
            "meaning_english": "Where is my house?",
            "confidence": 0.97,
            "lesson": "veedu means house; evida asks where",
            "provider": "gemini:gemini-3.5-flash",
        }

        result = prepare_user_input("ente veedu evida")

        self.assertEqual(result.meaning_english, "Where is my house?")
        self.assertTrue(result.provider.startswith("teacher:"))
        save_teacher_example.assert_called_once()
        save_language_cache.assert_called_once()


if __name__ == "__main__":
    unittest.main()
