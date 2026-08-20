import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import ContextBus, NexaKernel, RiskTier, SkillRegistry
from skills.github_skill import GitHubSkill
from workspace import WorkspaceManager


class FakeBridge:
    def __init__(self, *, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.calls = []

    def run(self, executable, args=(), *, cwd=None, timeout=None, env_overrides=None):
        self.calls.append(
            {
                "executable": str(executable),
                "args": tuple(args),
                "cwd": None if cwd is None else str(cwd),
            }
        )
        return SimpleNamespace(
            args=(str(executable), *tuple(args)),
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
            ok=self.returncode == 0,
        )


class GitHubSkillTests(unittest.TestCase):
    def _skill(self, root: Path, bridge=None):
        manager = WorkspaceManager([root])
        bus = ContextBus()
        return GitHubSkill(manager, bus, bridge=bridge or FakeBridge()), manager, bus

    def test_remote_mutations_are_declared_remote_risk(self):
        with tempfile.TemporaryDirectory() as temp:
            skill, _, _ = self._skill(Path(temp))
            self.assertEqual(skill.metadata.operation("clone").risk, RiskTier.REMOTE)
            self.assertEqual(skill.metadata.operation("create_repo").risk, RiskTier.REMOTE)
            self.assertEqual(skill.metadata.operation("create_pr").risk, RiskTier.REMOTE)

    def test_create_repo_validation_rejects_unsafe_name(self):
        with tempfile.TemporaryDirectory() as temp:
            skill, _, _ = self._skill(Path(temp))
            with self.assertRaises(ValueError):
                skill.validate(
                    "create_repo",
                    {"name": "../escape", "visibility": "private", "clone": False},
                    {},
                )

    def test_repo_create_uses_allowlisted_argument_array(self):
        with tempfile.TemporaryDirectory() as temp:
            bridge = FakeBridge(stdout="https://github.com/example/demo")
            skill, _, _ = self._skill(Path(temp), bridge=bridge)
            params = skill.validate(
                "create_repo",
                {"name": "demo", "visibility": "private", "clone": False},
                {},
            )
            result = skill.execute("create_repo", params, {})

            self.assertTrue(result.success)
            self.assertEqual(len(bridge.calls), 1)
            call = bridge.calls[0]
            self.assertEqual(call["executable"], "gh")
            self.assertEqual(call["args"], ("repo", "create", "demo", "--private"))
            self.assertIsNone(call["cwd"])

    def test_kernel_pauses_remote_repo_creation_for_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            skill, _, _ = self._skill(Path(temp), bridge=FakeBridge())
            registry = SkillRegistry()
            registry.register(skill)
            kernel = NexaKernel(registry=registry)

            response = kernel.process("github repo create demo private")

            self.assertEqual(response.status, "confirmation_required")
            self.assertIsNotNone(response.pending_action)
            self.assertEqual(response.pending_action.skill_name, "github")
            self.assertEqual(response.pending_action.operation, "create_repo")
            self.assertEqual(response.pending_action.params["name"], "demo")
            self.assertEqual(response.pending_action.params["visibility"], "private")

    def test_clone_destination_is_confined_to_configured_root(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            skill, _, _ = self._skill(root)
            params = skill.validate("clone", {"repo": "owner/demo"}, {})
            destination = params["destination"]
            self.assertTrue(destination.is_relative_to(root))
            self.assertEqual(destination.name, "demo")


if __name__ == "__main__":
    unittest.main()
