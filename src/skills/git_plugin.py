from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from core import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from git_skill import GitSkill, GitSkillError, validate_branch_name, validate_commit_message, validate_stage_path


class GitPlugin:
    """Kernel-native adapter around the reviewed allow-listed GitSkill."""

    def __init__(self) -> None:
        self.metadata = SkillMetadata(
            name="git",
            version="0.2.0",
            description="Safe Git operations scoped to the active workspace repository",
            operations=(
                OperationSpec("status", "Inspect Git status", RiskTier.READ),
                OperationSpec("branch", "Inspect current branch", RiskTier.READ),
                OperationSpec("history", "Inspect recent commits", RiskTier.READ),
                OperationSpec("diff", "Inspect unstaged changes", RiskTier.READ),
                OperationSpec("staged_diff", "Inspect staged changes", RiskTier.READ),
                OperationSpec("conflicts", "Inspect unresolved conflict files", RiskTier.READ),
                OperationSpec("stage", "Stage a repository-relative path", RiskTier.MUTATE),
                OperationSpec("commit", "Create a local commit", RiskTier.MUTATE),
                OperationSpec("create_branch", "Create and switch to a local branch", RiskTier.MUTATE),
                OperationSpec("switch_branch", "Switch local branch", RiskTier.MUTATE),
                OperationSpec("pull", "Fast-forward-only pull", RiskTier.REMOTE),
                OperationSpec("push", "Push current branch", RiskTier.REMOTE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = " ".join(text.strip().split())
        lowered = normalized.lower()
        exact = {
            "git status": "status",
            "/git status": "status",
            "git status nokku": "status",
            "current branch": "branch",
            "/git branch": "branch",
            "recent commits": "history",
            "/git history": "history",
            "changes nokku": "diff",
            "/git diff": "diff",
            "staged changes nokku": "staged_diff",
            "/git staged-diff": "staged_diff",
            "conflicts nokku": "conflicts",
            "/git conflicts": "conflicts",
            "git pull cheyyu": "pull",
            "/git pull": "pull",
            "githubilek push cheyyu": "push",
            "/git push": "push",
        }
        if lowered in exact:
            return SkillMatch("git", exact[lowered])

        match = re.fullmatch(r"(?:/git\s+stage|stage)\s+(.+)", normalized, re.IGNORECASE)
        if match:
            return SkillMatch("git", "stage", {"path": match.group(1).strip()})
        if lowered == "ith stage cheyyu":
            return SkillMatch("git", "stage", {"path": "."})

        match = re.fullmatch(
            r'(?:/git\s+commit|commit(?:\s+message)?)\s+["\'](.+)["\'](?:\s+vechu\s+commit\s+cheyyu)?',
            normalized,
            re.IGNORECASE,
        )
        if match:
            return SkillMatch("git", "commit", {"message": match.group(1)})

        for pattern, operation in (
            (r"(?:/git\s+branch-create|create\s+branch)\s+([A-Za-z0-9._/-]+)", "create_branch"),
            (r"puthiya\s+branch\s+(?:thudang|create)\s+[\"']?([A-Za-z0-9._/-]+)[\"']?", "create_branch"),
            (r"(?:/git\s+branch-switch|switch\s+branch)\s+([A-Za-z0-9._/-]+)", "switch_branch"),
            (r"branch\s+maatt\s+[\"']?([A-Za-z0-9._/-]+)[\"']?", "switch_branch"),
        ):
            match = re.fullmatch(pattern, normalized, re.IGNORECASE)
            if match:
                return SkillMatch("git", operation, {"branch": match.group(1)})
        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        repo = self._repo(context)
        skill = GitSkill(repo)
        if not skill.is_repository():
            raise ValueError("active workspace is not a Git repository")

        conflicts = skill.conflict_files()
        if not conflicts.ok:
            raise ValueError(conflicts.stderr or "failed to inspect Git conflicts")
        has_conflicts = bool(conflicts.stdout.strip())

        if operation in {"status", "branch", "history", "diff", "staged_diff", "conflicts"}:
            return {"repo": repo}

        if has_conflicts:
            raise ValueError("unresolved Git conflicts block mutating operations")

        status = skill.status()
        if not status.ok:
            raise ValueError(status.stderr or "failed to inspect Git status")

        if operation == "stage":
            return {"repo": repo, "path": validate_stage_path(str(params.get("path", ".")))}
        if operation == "commit":
            message = validate_commit_message(str(params.get("message", "")))
            staged = skill.diff(staged=True)
            if not staged.ok:
                raise ValueError(staged.stderr or "failed to inspect staged changes")
            if not staged.stdout.strip():
                raise ValueError("no staged changes to commit")
            return {"repo": repo, "message": message}
        if operation in {"create_branch", "switch_branch"}:
            branch = validate_branch_name(str(params.get("branch", "")))
            if self._working_tree_dirty(status.stdout):
                raise ValueError("working tree must be clean before branch mutation")
            return {"repo": repo, "branch": branch}
        if operation == "pull":
            if self._working_tree_dirty(status.stdout):
                raise ValueError("working tree must be clean before pull")
            branch_result = skill.current_branch()
            if not branch_result.ok or not branch_result.stdout.strip():
                raise ValueError(branch_result.stderr or "cannot determine current branch")
            return {"repo": repo, "branch": validate_branch_name(branch_result.stdout.strip())}
        if operation == "push":
            branch_result = skill.current_branch()
            if not branch_result.ok or not branch_result.stdout.strip():
                raise ValueError(branch_result.stderr or "cannot determine current branch")
            return {"repo": repo, "branch": validate_branch_name(branch_result.stdout.strip())}
        raise ValueError("unknown Git operation")

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        skill = GitSkill(Path(params["repo"]))
        try:
            if operation == "status":
                result = skill.status()
            elif operation == "branch":
                result = skill.current_branch()
            elif operation == "history":
                result = skill.history(10)
            elif operation == "diff":
                result = skill.diff(False)
            elif operation == "staged_diff":
                result = skill.diff(True)
            elif operation == "conflicts":
                result = skill.conflict_files()
            elif operation == "stage":
                result = skill.stage(str(params["path"]))
            elif operation == "commit":
                result = skill.commit(str(params["message"]))
            elif operation == "create_branch":
                result = skill.create_branch(str(params["branch"]))
            elif operation == "switch_branch":
                result = skill.switch_branch(str(params["branch"]))
            elif operation == "pull":
                result = skill.pull_ff_only(str(params["branch"]))
            elif operation == "push":
                result = skill.push(str(params["branch"]))
            else:
                return ExecutionResult(False, "unknown Git operation", error="unknown operation")
        except GitSkillError as exc:
            return ExecutionResult(False, str(exc), error=str(exc))

        message = result.stdout or result.stderr or ("Git command succeeded" if result.ok else "Git command failed")
        return ExecutionResult(
            result.ok,
            message,
            data={"args": result.args, "stdout": result.stdout, "stderr": result.stderr},
            error=None if result.ok else (result.stderr or "Git command failed"),
        )

    @staticmethod
    def _repo(context: Mapping[str, Any]) -> Path:
        raw = context.get("active_workspace_path")
        if not raw:
            raise ValueError("no active workspace selected")
        repo = Path(str(raw)).expanduser().resolve()
        if not repo.exists() or not repo.is_dir():
            raise ValueError("active workspace does not exist")
        return repo

    @staticmethod
    def _working_tree_dirty(status_output: str) -> bool:
        lines = [line for line in status_output.splitlines() if line.strip()]
        return any(not line.startswith("##") for line in lines)
