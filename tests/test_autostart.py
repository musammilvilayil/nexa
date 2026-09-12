import sys
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.autostart import get_autostart_command, is_autostart_enabled
from ui.server import get_system_metrics


class TestAutostartAndMetrics(unittest.TestCase):
    def test_get_system_metrics(self):
        metrics = get_system_metrics()

        self.assertIn("timestamp", metrics)
        self.assertIn("cpu", metrics)
        self.assertIn("ram", metrics)
        self.assertIn("drives", metrics)

        # Verify CPU cores
        self.assertGreater(metrics["cpu"]["cores"], 0)

        # Verify RAM structure
        self.assertIn("total_gb", metrics["ram"])
        self.assertIn("used_percent", metrics["ram"])

        # Verify drive structure
        drives = metrics["drives"]
        if "C:" in drives:
            c = drives["C:"]
            self.assertIn("free_gb", c)
            self.assertIn("total_gb", c)
            self.assertIn("free_percent", c)

    def test_autostart_functions_safe(self):
        # Verification that functions do not raise unexpected exceptions
        enabled = is_autostart_enabled()
        self.assertIsInstance(enabled, bool)

        cmd = get_autostart_command()
        if cmd is not None:
            self.assertIsInstance(cmd, str)


if __name__ == "__main__":
    unittest.main()
