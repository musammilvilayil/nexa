import subprocess
import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from git_skill import (
    GitSkill,
    GitSkillError,
    validate_branch_name,
    validate_commit_message,
    validate_stage_path,
)


class FakeRunner:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.commands = []

    def __call__(self, command):
        self.commands.append(list(command))
        return subprocess.CompletedProcess(
            command,
            self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


class GitSkillValidationTests(unittest.TestCase):
    def test_valid_branch_name(self):
        self.assertEqual(validate_branch_name("feature/git-skill"), "feature/git-skill")

    def test_rejects_unsafe_branch_name(self):
        for value in ["", "-bad", "../main", "a..b", "foo//bar", "foo/"]:
            with self.subTest(value=value):
                with self.assertRaises(GitSkillError):
                    validate_branch_name(value)

    def test_rejects_empty_commit_message(self):
        with self.assertRaises(GitSkillError):
            validate_commit_message("   ")

    def test_stage_path_must_stay_inside_repo(self):
        for value in ["../secret.txt", "-A"]:
            with self.subTest(value=value):
                with self.assertRaises(GitSkillError):
                    validate_stage_path(value)


class GitSkillCommandTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner(stdout="ok\n")
        self.skill = GitSkill(".", runner=self.runner)

    def last_git_args(self):
        return self.runner.commands[-1][3:]

    def test_status_is_allowlisted(self):
        self.skill.status()
        self.assertEqual(self.last_git_args(), ["status", "--short", "--branch"])

    def test_current_branch(self):
        self.skill.current_branch()
        self.assertEqual(self.last_git_args(), ["branch", "--show-current"])

    def test_head_commit(self):
        self.skill.head_commit()
        self.assertEqual(self.last_git_args(), ["rev-parse", "HEAD"])

    def test_unstaged_diff(self):
        self.skill.diff()
        self.assertEqual(self.last_git_args(), ["diff"])

    def test_staged_diff(self):
        self.skill.diff(staged=True)
        self.assertEqual(self.last_git_args(), ["diff", "--cached"])

    def test_history_limit_is_bounded(self):
        self.skill.history(25)
        self.assertEqual(self.last_git_args(), ["log", "-25", "--oneline", "--decorate"])
        with self.assertRaises(GitSkillError):
            self.skill.history(101)

    def test_fetch_prunes(self):
        self.skill.fetch()
        self.assertEqual(self.last_git_args(), ["fetch", "origin", "--prune"])

    def test_pull_is_fast_forward_only(self):
        self.skill.pull_ff_only("main")
        self.assertEqual(self.last_git_args(), ["pull", "--ff-only", "origin", "main"])

    def test_create_branch_uses_switch(self):
        self.skill.create_branch("feature/test")
        self.assertEqual(self.last_git_args(), ["switch", "-c", "feature/test"])

    def test_stage_inserts_option_terminator(self):
        self.skill.stage("src/nexa.py")
        self.assertEqual(self.last_git_args(), ["add", "--", "src/nexa.py"])

    def test_commit_message_is_single_argument(self):
        self.skill.commit("Fix parser; echo unsafe")
        self.assertEqual(self.last_git_args(), ["commit", "-m", "Fix parser; echo unsafe"])

    def test_push_has_no_force_flag(self):
        self.skill.push("main")
        args = self.last_git_args()
        self.assertEqual(args, ["push", "origin", "main"])
        self.assertNotIn("--force", args)

    def test_push_set_upstream(self):
        self.skill.push("feature/test", set_upstream=True)
        self.assertEqual(self.last_git_args(), ["push", "-u", "origin", "feature/test"])

    def test_conflict_detection(self):
        self.skill.conflict_files()
        self.assertEqual(self.last_git_args(), ["diff", "--name-only", "--diff-filter=U"])

    def test_shell_is_never_exposed_to_model_text(self):
        malicious = "hello && del C:\\important.txt"
        self.skill.commit(malicious)
        command = self.runner.commands[-1]
        self.assertEqual(command[-1], malicious)
        self.assertEqual(command[0], "git")


if __name__ == "__main__":
    unittest.main()
