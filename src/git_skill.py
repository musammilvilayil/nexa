from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


class GitSkillError(RuntimeError):
    pass


@dataclass(frozen=True)
class GitResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0


Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def _default_runner(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        capture_output=True,
        text=True,
        shell=False,
        check=False,
    )


def validate_branch_name(branch: str) -> str:
    branch = branch.strip()
    if not branch or not BRANCH_RE.fullmatch(branch):
        raise GitSkillError("Invalid Git branch name")
    if branch.startswith("-") or ".." in branch or "//" in branch or branch.endswith("/"):
        raise GitSkillError("Unsafe Git branch name")
    return branch


def validate_commit_message(message: str) -> str:
    message = message.strip()
    if not message:
        raise GitSkillError("Commit message cannot be empty")
    if "\x00" in message:
        raise GitSkillError("Commit message contains an invalid character")
    return message


def validate_stage_path(path: str) -> str:
    path = path.strip()
    if path == ".":
        return path
    if not path or path.startswith("-"):
        raise GitSkillError("Unsafe stage path")

    candidate = Path(path)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise GitSkillError("Stage path must stay inside the repository")
    return path


class GitSkill:
    """Deterministic, allow-listed Git operator for NEXA.

    The class intentionally does not expose an arbitrary `git <args>` API.
    Every operation below maps to a reviewed command and executes with
    `shell=False`, so model text can never become a shell command directly.
    """

    def __init__(self, repo_path: str | Path, runner: Runner | None = None):
        self.repo_path = Path(repo_path).resolve()
        self._runner = runner or _default_runner

    def _run(self, *git_args: str) -> GitResult:
        command = ["git", "-C", str(self.repo_path), *git_args]
        completed = self._runner(command)
        return GitResult(
            args=tuple(git_args),
            returncode=completed.returncode,
            stdout=(completed.stdout or "").strip(),
            stderr=(completed.stderr or "").strip(),
        )

    def is_repository(self) -> bool:
        result = self._run("rev-parse", "--is-inside-work-tree")
        return result.ok and result.stdout.lower() == "true"

    def status(self) -> GitResult:
        return self._run("status", "--short", "--branch")

    def current_branch(self) -> GitResult:
        return self._run("branch", "--show-current")

    def head_commit(self) -> GitResult:
        return self._run("rev-parse", "HEAD")

    def diff(self, staged: bool = False) -> GitResult:
        if staged:
            return self._run("diff", "--cached")
        return self._run("diff")

    def history(self, limit: int = 10) -> GitResult:
        if not isinstance(limit, int) or not 1 <= limit <= 100:
            raise GitSkillError("History limit must be between 1 and 100")
        return self._run("log", f"-{limit}", "--oneline", "--decorate")

    def fetch(self, remote: str = "origin") -> GitResult:
        remote = self._validate_remote(remote)
        return self._run("fetch", remote, "--prune")

    def pull_ff_only(self, branch: str, remote: str = "origin") -> GitResult:
        branch = validate_branch_name(branch)
        remote = self._validate_remote(remote)
        return self._run("pull", "--ff-only", remote, branch)

    def create_branch(self, branch: str) -> GitResult:
        branch = validate_branch_name(branch)
        return self._run("switch", "-c", branch)

    def switch_branch(self, branch: str) -> GitResult:
        branch = validate_branch_name(branch)
        return self._run("switch", branch)

    def stage(self, path: str = ".") -> GitResult:
        path = validate_stage_path(path)
        return self._run("add", "--", path)

    def commit(self, message: str) -> GitResult:
        message = validate_commit_message(message)
        return self._run("commit", "-m", message)

    def push(self, branch: str, remote: str = "origin", set_upstream: bool = False) -> GitResult:
        branch = validate_branch_name(branch)
        remote = self._validate_remote(remote)
        if set_upstream:
            return self._run("push", "-u", remote, branch)
        return self._run("push", remote, branch)

    def conflict_files(self) -> GitResult:
        return self._run("diff", "--name-only", "--diff-filter=U")

    @staticmethod
    def _validate_remote(remote: str) -> str:
        remote = remote.strip()
        if not remote or remote.startswith("-") or not re.fullmatch(r"[A-Za-z0-9._-]+", remote):
            raise GitSkillError("Invalid Git remote name")
        return remote
