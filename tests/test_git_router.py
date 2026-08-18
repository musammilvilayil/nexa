import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from git_router import detect_git_intent, handle_git_command
from git_skill import GitResult


def result(*args, stdout="", stderr="", returncode=0):
    return GitResult(tuple(args), returncode, stdout, stderr)


class FakeGitSkill:
    def __init__(self, status_stdout="## main...origin/main", conflict_stdout=""):
        self.status_stdout = status_stdout
        self.conflict_stdout = conflict_stdout
        self.pull_calls = []
        self.stage_calls = []
        self.commit_calls = []
        self.push_calls = []
        self.create_branch_calls = []
        self.switch_branch_calls = []
        self.staged_diff_stdout = ""
        self.current_branch_name = "main"

    def status(self):
        return result("status", stdout=self.status_stdout)

    def current_branch(self):
        return result("branch", stdout=self.current_branch_name)

    def history(self, limit=5):
        return result("log", stdout="abc123 latest commit")

    def diff(self, staged=False):
        if staged:
            return result("diff", "--cached", stdout=self.staged_diff_stdout)
        return result("diff", stdout="")

    def conflict_files(self):
        return result("diff", "--name-only", "--diff-filter=U", stdout=self.conflict_stdout)

    def pull_ff_only(self, branch, remote="origin"):
        self.pull_calls.append((branch, remote))
        return result("pull", stdout="Already up to date.")

    def create_branch(self, branch):
        self.create_branch_calls.append(branch)
        self.current_branch_name = branch
        return result("switch", "-c", branch, stdout=f"Switched to a new branch '{branch}'")

    def switch_branch(self, branch):
        self.switch_branch_calls.append(branch)
        self.current_branch_name = branch
        return result("switch", branch, stdout=f"Switched to branch '{branch}'")

    def stage(self, path="."):
        self.stage_calls.append(path)
        self.staged_diff_stdout = "diff --git a/file b/file"
        return result("add")

    def commit(self, message):
        self.commit_calls.append(message)
        return result("commit", stdout="[main abc123] " + message)

    def push(self, branch, remote="origin", set_upstream=False):
        self.push_calls.append((branch, remote, set_upstream))
        return result("push", stdout="main -> main")


class GitRouterTests(unittest.TestCase):
    def test_detects_natural_manglish_pull(self):
        self.assertEqual(detect_git_intent("git pull cheyyu"), "pull")
        self.assertEqual(detect_git_intent("repo update cheyyu"), "pull")

    def test_unrelated_chat_is_not_a_git_command(self):
        self.assertIsNone(detect_git_intent("oru platform build cheythalo"))

    def test_status_routes_to_git_skill(self):
        skill = FakeGitSkill()
        reply = handle_git_command("git status nokku", skill)
        self.assertIn("## main...origin/main", reply)

    def test_clean_pull_uses_current_branch_and_ff_only_skill(self):
        skill = FakeGitSkill()
        reply = handle_git_command("git pull cheyyu", skill)
        self.assertEqual(skill.pull_calls, [("main", "origin")])
        self.assertIn("Git pull complete", reply)

    def test_dirty_working_tree_blocks_pull(self):
        skill = FakeGitSkill("## main...origin/main\n M src/nexa.py")
        reply = handle_git_command("repo update cheyyu", skill)
        self.assertEqual(skill.pull_calls, [])
        self.assertIn("Local changes undu", reply)

    def test_read_only_commands_are_supported(self):
        skill = FakeGitSkill()
        self.assertIn("main", handle_git_command("current branch", skill))
        self.assertIn("abc123", handle_git_command("recent commits", skill))
        self.assertIn("No unstaged changes", handle_git_command("git diff", skill))
        self.assertIn("No unstaged changes", handle_git_command("changes nokku", skill))
        self.assertIn("conflicts onnum illa", handle_git_command("conflicts nokku", skill))

    def test_stage_all_requires_local_changes(self):
        clean = FakeGitSkill()
        self.assertIn("changes onnum illa", handle_git_command("ith stage cheyyu", clean))
        self.assertEqual(clean.stage_calls, [])

        dirty = FakeGitSkill("## main...origin/main\n M src/nexa.py")
        reply = handle_git_command("ith stage cheyyu", dirty)
        self.assertEqual(dirty.stage_calls, ["."])
        self.assertIn("staged successfully", reply)

    def test_commit_requires_real_message_and_staged_changes(self):
        skill = FakeGitSkill()
        reply = handle_git_command('commit message "..." vechu commit cheyyu', skill)
        self.assertIn("Commit message clear alla", reply)
        self.assertEqual(skill.commit_calls, [])

        reply = handle_git_command('commit message "fix git router" vechu commit cheyyu', skill)
        self.assertIn("staged changes onnum illa", reply)

        skill.staged_diff_stdout = "diff --git a/file b/file"
        reply = handle_git_command('commit message "fix git router" vechu commit cheyyu', skill)
        self.assertEqual(skill.commit_calls, ["fix git router"])
        self.assertIn("Git commit complete", reply)

    def test_push_uses_current_branch_without_force(self):
        skill = FakeGitSkill()
        reply = handle_git_command("githubilek push cheyyu", skill)
        self.assertEqual(skill.push_calls, [("main", "origin", False)])
        self.assertIn("Git push complete", reply)

    def test_branch_create_and_switch_intents(self):
        self.assertEqual(detect_git_intent("test-safe branch create cheyyu"), "create_branch")
        self.assertEqual(detect_git_intent("test-safe branchilek switch cheyyu"), "switch_branch")

        skill = FakeGitSkill()
        reply = handle_git_command("test-safe branch create cheyyu", skill)
        self.assertEqual(skill.create_branch_calls, ["test-safe"])
        self.assertIn("created and switched", reply)

        reply = handle_git_command("main branchilek switch cheyyu", skill)
        self.assertEqual(skill.switch_branch_calls, ["main"])
        self.assertIn("branch switched", reply)

    def test_dirty_tree_blocks_branch_mutation(self):
        skill = FakeGitSkill("## main...origin/main\n M README.md")
        reply = handle_git_command("test-safe branch create cheyyu", skill)
        self.assertEqual(skill.create_branch_calls, [])
        self.assertIn("Local changes undu", reply)

        reply = handle_git_command("main branchilek switch cheyyu", skill)
        self.assertEqual(skill.switch_branch_calls, [])
        self.assertIn("Local changes undu", reply)

    def test_conflicts_block_mutating_git_actions(self):
        skill = FakeGitSkill(conflict_stdout="src/nexa.py")

        self.assertIn("src/nexa.py", handle_git_command("conflicts nokku", skill))
        self.assertIn("conflicts undu", handle_git_command("git pull cheyyu", skill))
        self.assertIn("conflicts undu", handle_git_command("ith stage cheyyu", skill))
        self.assertIn(
            "conflicts undu",
            handle_git_command('commit message "resolve later" vechu commit cheyyu', skill),
        )
        self.assertIn("conflicts undu", handle_git_command("githubilek push cheyyu", skill))
        self.assertIn("conflicts undu", handle_git_command("test-safe branch create cheyyu", skill))
        self.assertIn("conflicts undu", handle_git_command("main branchilek switch cheyyu", skill))

        self.assertEqual(skill.pull_calls, [])
        self.assertEqual(skill.stage_calls, [])
        self.assertEqual(skill.commit_calls, [])
        self.assertEqual(skill.push_calls, [])
        self.assertEqual(skill.create_branch_calls, [])
        self.assertEqual(skill.switch_branch_calls, [])

    def test_new_natural_language_intents_are_detected(self):
        self.assertEqual(detect_git_intent("changes nokku"), "diff")
        self.assertEqual(detect_git_intent("ith stage cheyyu"), "stage")
        self.assertEqual(
            detect_git_intent('commit message "fix git router" vechu commit cheyyu'),
            "commit",
        )
        self.assertEqual(detect_git_intent("githubilek push cheyyu"), "push")
        self.assertEqual(detect_git_intent("conflicts nokku"), "conflicts")


if __name__ == "__main__":
    unittest.main()
