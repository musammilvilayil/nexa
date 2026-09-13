import sys
import tempfile
import unittest
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ui.instance_lock import acquire_instance_lock, is_another_instance_running, release_instance_lock


class TestInstanceLock(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.lock_file = Path(self.temp_dir.name) / "test.lock"

    def tearDown(self):
        release_instance_lock()
        self.temp_dir.cleanup()

    def test_acquire_and_release(self):
        # First acquire should succeed
        ok1 = acquire_instance_lock(self.lock_file)
        self.assertTrue(ok1)

        # Release lock
        release_instance_lock()

        # Re-acquire should succeed after release
        ok2 = acquire_instance_lock(self.lock_file)
        self.assertTrue(ok2)


if __name__ == "__main__":
    unittest.main()
