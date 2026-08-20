from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from bridges import SubprocessBridge, SubprocessBridgeError
from core import ContextBus, ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from workspace import WorkspaceManager


_REPO_REF_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,127}$")


class GitHubSkill:
    """Allow-listed GitHub CLI operations with no arbitrary gh argument escape hatch."""

    def __init__(
        self,
        workspace_manager: WorkspaceManager,
        context_bus: ContextBus,
        bridge: SubprocessBridge | None = None,
    ) -> None:
        self.workspace_manager = workspace_manager
        self.context_bus = context_bus
        self.bridge = bridge or SubprocessBridge(
            ["gh", "gh.exe"],
            default_timeout=60.0,
            inherit_environment=False,
        )
        self.metadata = SkillMetadata(
            name="github",
            version="0.2.0",
            description="Safe GitHub platform operations through authenticated gh CLI",
            operations=(
                OperationSpec("auth_status", "Inspect gh authentication", RiskTier.READ),
                OperationSpec("list_repos", "List accessible repositories", RiskTier.READ),
                OperationSpec("repo_view", "Inspect one GitHub repository", RiskTier.READ),
                OperationSpec("clone", "Clone a repository into a configured workspace root", RiskTier.REMOTE),
                OperationSpec("create_repo", "Create a remote repository and optionally clone it", RiskTier.REMOTE),
                OperationSpec("create_pr", "Create a pull request from the active repository", RiskTier.REMOTE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = " ".join(text.strip().split())
        lowered = normalized.lower()
        if lowered in {"github auth status", "gh auth status", "/github auth"}:
            return SkillMatch("github", "auth_status")
        if lowered in {"github repos", "github repo list", "gh repo list", "/github repos"}:
            return SkillMatch("github", "list_repos")

        match = re.fullmatch(r"(?:/github\s+view|github\s+repo\s+view)\s+([^\s]+)", normalized, re.IGNORECASE)
        if match:
            return SkillMatch("github", "repo_view", {"repo": match.group(1)})

        match = re.fullmatch(r"(?:/github\s+clone|github\s+clone)\s+([^\s]+)", normalized, re.IGNORECASE)
        if match:
            return SkillMatch("github", "clone", {"repo": match.group(1)})

        match = re.fullmatch(
            r"(?:/github\s+create|github\s+repo\s+create)\s+([A-Za-z0-9_.-]+)\s+(public|private)(?:\s+(clone))?",
            normalized,
            re.IGNORECASE,
        )
        if match:
            return SkillMatch(
                "github",
                "create_repo",
                {
                    "name": match.group(1),
                    "visibility": match.group(2).lower(),
                    "clone": bool(match.group(3)),
                },
            )

        match = re.fullmatch(
            r"(?:/github\s+pr|github\s+pr\s+create)\s+base\s+([A-Za-z0-9._/-]+)\s+title\s+(.+)",
            normalized,
            re.IGNORECASE,
        )
        if match:
            return SkillMatch(
                "github",
                "create_pr",
                {"base": match.group(1), "title": match.group(2).strip()},
            )
        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation in {"auth_status", "list_repos"}:
            return {}
        if operation in {"repo_view", "clone"}:
            repo = str(params.get("repo", "")).strip()
            if not _REPO_REF_RE.fullmatch(repo):
                raise ValueError("repository must be owner/name")
            if operation == "clone":
                target_root = self._clone_root()
                name = repo.rsplit("/", 1)[1]
                destination = (target_root / name).resolve()
                if not destination.is_relative_to(target_root):
                    raise ValueError("clone destination escaped workspace root")
                if destination.exists():
                    raise ValueError("clone destination already exists")
                return {"repo": repo, "destination": destination}
            return {"repo": repo}
        if operation == "create_repo":
            name = str(params.get("name", "")).strip()
            if not _REPO_NAME_RE.fullmatch(name) or name.startswith("."):
                raise ValueError("invalid GitHub repository name")
            visibility = str(params.get("visibility", "")).strip().lower()
            if visibility not in {"public", "private"}:
                raise ValueError("visibility must be public or private")
            clone = bool(params.get("clone", False))
            destination = None
            if clone:
                root = self._clone_root()
                destination = (root / name).resolve()
                if not destination.is_relative_to(root):
                    raise ValueError("repository destination escaped workspace root")
                if destination.exists():
                    raise ValueError("repository destination already exists")
            return {"name": name, "visibility": visibility, "clone": clone, "destination": destination}
        if operation == "create_pr":
            repo = self._active_repo(context)
            base = str(params.get("base", "")).strip()
            if not _BRANCH_RE.fullmatch(base) or ".." in base or "//" in base:
                raise ValueError("invalid PR base branch")
            title = str(params.get("title", "")).strip()
            if not title or len(title) > 256 or "\x00" in title:
                raise ValueError("invalid PR title")
            return {"repo": repo, "base": base, "title": title}
        raise ValueError("unknown GitHub operation")

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        try:
            if operation == "auth_status":
                result = self.bridge.run("gh", ["auth", "status"])
                return self._result(result, "GitHub authentication inspected")

            if operation == "list_repos":
                result = self.bridge.run(
                    "gh",
                    [
                        "repo",
                        "list",
                        "--limit",
                        "100",
                        "--json",
                        "nameWithOwner,isPrivate,url,defaultBranchRef",
                    ],
                )
                if not result.ok:
                    return self._result(result, "GitHub repository listing failed")
                try:
                    data = json.loads(result.stdout or "[]")
                except json.JSONDecodeError:
                    data = result.stdout
                return ExecutionResult(True, "GitHub repositories listed", data=data)

            if operation == "repo_view":
                result = self.bridge.run(
                    "gh",
                    [
                        "repo",
                        "view",
                        str(params["repo"]),
                        "--json",
                        "nameWithOwner,isPrivate,url,defaultBranchRef,description",
                    ],
                )
                if not result.ok:
                    return self._result(result, "GitHub repository inspection failed")
                try:
                    data = json.loads(result.stdout or "{}")
                except json.JSONDecodeError:
                    data = result.stdout
                return ExecutionResult(True, "GitHub repository inspected", data=data)

            if operation == "clone":
                destination: Path = Path(params["destination"]).resolve()
                root = self._clone_root().resolve()
                if not destination.is_relative_to(root):
                    return ExecutionResult(False, "clone destination escaped workspace root", error="unsafe destination")
                if destination.exists():
                    return ExecutionResult(False, "clone destination appeared after validation; submit again", error="stale precondition")
                result = self.bridge.run(
                    "gh",
                    ["repo", "clone", str(params["repo"]), str(destination)],
                    cwd=destination.parent,
                )
                if result.ok:
                    self._refresh_and_activate(destination)
                return self._result(result, "Repository cloned" if result.ok else "Repository clone failed")

            if operation == "create_repo":
                args = ["repo", "create", str(params["name"]), f"--{params['visibility']}"]
                destination: Path | None = params.get("destination")
                if bool(params["clone"]):
                    if destination is None:
                        return ExecutionResult(False, "clone destination missing", error="invalid validated state")
                    destination = Path(destination).resolve()
                    root = self._clone_root().resolve()
                    if not destination.is_relative_to(root):
                        return ExecutionResult(False, "repository destination escaped workspace root", error="unsafe destination")
                    if destination.exists():
                        return ExecutionResult(False, "repository destination appeared after validation; submit again", error="stale precondition")
                    args.append("--clone")
                    result = self.bridge.run("gh", args, cwd=destination.parent)
                    if result.ok and destination.exists():
                        self._refresh_and_activate(destination)
                else:
                    result = self.bridge.run("gh", args)
                return self._result(result, "GitHub repository created" if result.ok else "Repository creation failed")

            if operation == "create_pr":
                repo = Path(params["repo"]).resolve()
                if not repo.exists() or not repo.is_dir() or not ((repo / ".git").exists()):
                    return ExecutionResult(False, "active repository changed or disappeared; submit again", error="stale precondition")
                result = self.bridge.run(
                    "gh",
                    ["pr", "create", "--base", str(params["base"]), "--title", str(params["title"]), "--body", ""],
                    cwd=repo,
                )
                return self._result(result, "Pull request created" if result.ok else "Pull request creation failed")
        except SubprocessBridgeError as exc:
            return ExecutionResult(False, str(exc), error=str(exc))

        return ExecutionResult(False, "unknown GitHub operation", error="unknown operation")

    def _clone_root(self) -> Path:
        if not self.workspace_manager.roots:
            raise ValueError("no configured workspace root")
        return self.workspace_manager.roots[0]

    @staticmethod
    def _active_repo(context: Mapping[str, Any]) -> Path:
        raw = context.get("active_workspace_path")
        if not raw:
            raise ValueError("no active workspace selected")
        repo = Path(str(raw)).expanduser().resolve()
        if not repo.exists() or not repo.is_dir():
            raise ValueError("active workspace does not exist")
        return repo

    def _refresh_and_activate(self, path: Path) -> None:
        self.workspace_manager.discover()
        repo = self.workspace_manager.switch(str(path.resolve()))
        self.context_bus.set_active_workspace(repo.path)

    @staticmethod
    def _result(result, success_message: str) -> ExecutionResult:
        message = result.stdout.strip() or result.stderr.strip() or success_message
        return ExecutionResult(
            result.ok,
            success_message if result.ok and not message else message,
            data={"args": result.args, "stdout": result.stdout, "stderr": result.stderr},
            error=None if result.ok else (result.stderr.strip() or "GitHub command failed"),
        )
