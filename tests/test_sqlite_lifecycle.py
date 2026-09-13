import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sqlite_utils import connect_sqlite


class SQLiteLifecycleTests(unittest.TestCase):
    def test_context_manager_commits_and_closes_connection(self):
        with tempfile.TemporaryDirectory() as temp:
            db_path = Path(temp) / "lifecycle.db"
            with connect_sqlite(db_path) as connection:
                connection.execute("CREATE TABLE items(value TEXT NOT NULL)")
                connection.execute("INSERT INTO items(value) VALUES ('ok')")

            with self.assertRaises(sqlite3.ProgrammingError):
                connection.execute("SELECT 1")

            with connect_sqlite(db_path) as verify:
                value = verify.execute("SELECT value FROM items").fetchone()["value"]
                self.assertEqual(value, "ok")


if __name__ == "__main__":
    unittest.main()
