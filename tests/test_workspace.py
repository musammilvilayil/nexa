import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from workspace import WorkspaceError, WorkspaceManager


class WorkspaceManagerTests(unittest.TestCase):
    def _repo(self, root: Path, relative: str) -> Path:
        repo = root / relative
        repo.mkdir(parents=True, exist_ok=True)
        (repo / ".git").mkdir()
        return repo.resolve()

    def test_discovers_repositories_under_configured_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            alpha = self._repo(root, "alpha")
            beta = self._repo(root, "group/beta")
            (root / "ordinary-folder").mkdir()

            manager = WorkspaceManager([root])
            repos = manager.discover()

            self.assertEqual({repo.path for repo in repos}, {alpha, beta})
            self.assertEqual({repo.name for repo in repos}, {"alpha", "beta"})

    def test_configured_root_can_itself_be_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / ".git").mkdir()

            manager = WorkspaceManager([root])
            repos = manager.discover()

            self.assertEqual(len(repos), 1)
            self.assertEqual(repos[0].path, root.resolve())

    def test_switch_is_case_insensitive_and_tracks_active_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = self._repo(root, "NEXA-Test")

            manager = WorkspaceManager([root])
            manager.discover()
            selected = manager.switch("nexa-test")

            self.assertEqual(selected.path, target)
            self.assertEqual(manager.require_active_repo().path, target)

    def test_absolute_path_switch_requires_discovered_repo(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = self._repo(root, "alpha")
            outside = Path(temp).parent / "not-a-workspace-repo"

            manager = WorkspaceManager([root])
            manager.discover()

            self.assertEqual(manager.switch(str(target)).path, target)
            with self.assertRaises(WorkspaceError):
                manager.switch(str(outside.resolve()))

    def test_duplicate_repo_names_are_ambiguous(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self._repo(root, "team-a/project")
            self._repo(root, "team-b/project")

            manager = WorkspaceManager([root])
            manager.discover()

            with self.assertRaisesRegex(WorkspaceError, "ambiguous"):
                manager.switch("project")

    def test_missing_active_repo_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = WorkspaceManager([temp])
            with self.assertRaisesRegex(WorkspaceError, "No active repository"):
                manager.require_active_repo()

    def test_invalid_workspace_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing"
            with self.assertRaisesRegex(WorkspaceError, "does not exist"):
                WorkspaceManager([missing])


if __name__ == "__main__":
    unittest.main()
