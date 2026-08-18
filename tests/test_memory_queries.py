import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from memory import extract_fact, identify_fact_query


class MemoryQueryTests(unittest.TestCase):
    def test_manglish_name_question_maps_to_name(self):
        self.assertEqual(identify_fact_query("ente peru entha"), "name")

    def test_english_name_question_maps_to_name(self):
        self.assertEqual(identify_fact_query("what is my name?"), "name")

    def test_manglish_favourite_color_question(self):
        self.assertEqual(
            identify_fact_query("ente favourite color entha"),
            "favourite_color",
        )

    def test_manglish_peru_fact_is_learned(self):
        self.assertEqual(
            extract_fact("ente peru Musammil aanu"),
            ("name", "musammil"),
        )


if __name__ == "__main__":
    unittest.main()
