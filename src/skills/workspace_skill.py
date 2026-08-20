from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from core import ContextBus, ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from workspace import WorkspaceManager


_SWITCH_PATTERNS = (
    re.compile(r"^repo\s+(.+?)\s+(?:il\s+)?switch\s+cheyyu$", re.IGNORECASE),
    re.compile(r"^switch\s+(?:to\s+)?repo\s+(.+)$", re.IGNORECASE),
    re.compile(r"^/repo\s+switch\s+(.+)$", re.IGNORECASE),
)


class WorkspaceSkill:
    """Kernel plugin that owns repository discovery and active-workspace context."""

    def __init__(self, manager: WorkspaceManager, context_bus: ContextBus) -> None:
        self.manager = manager
        self.context_bus = context_bus
        self.metadata = SkillMetadata(
            name="workspace",
            version="0.1.0",
            description="Discover, inspect, and switch explicitly configured repository workspaces",
            operations=(
                OperationSpec("list", "List discovered repositories", RiskTier.READ),
                OperationSpec("active", "Inspect active repository", RiskTier.READ),
                OperationSpec("switch", "Switch active repository context", RiskTier.MUTATE),
                OperationSpec("refresh", "Refresh repository discovery", RiskTier.READ),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = " ".join(text.strip().split())
        lowered = normalized.lower()
        if lowered in {"repos list cheyyu", "repo list cheyyu", "repositories list", "/repos", "/repo list"}:
            return SkillMatch("workspace", "list")
        if lowered in {"active repo", "current repo", "active workspace", "/repo active"}:
            return SkillMatch("workspace", "active")
        if lowered in {"repos refresh", "workspace refresh", "/repo refresh"}:
            return SkillMatch("workspace", "refresh")
        for pattern in _SWITCH_PATTERNS:
            match = pattern.fullmatch(normalized)
            if match is not None:
                return SkillMatch("workspace", "switch", {"query": match.group(1).strip()})
        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation in {"list", "active", "refresh"}:
            return {}
        if operation != "switch":
            raise ValueError("unknown workspace operation")
        query = str(params.get("query", "")).strip()
        if not query:
            raise ValueError("repository query required")
        if "\x00" in query or len(query) > 1024:
            raise ValueError("unsafe repository query")
        return {"query": query}

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        if operation == "refresh":
            repos = self.manager.discover()
            return ExecutionResult(True, f"Workspace refreshed: {len(repos)} repo(s)", self._repo_data(repos))

        if operation == "list":
            repos = self.manager.discover()
            return ExecutionResult(True, f"Found {len(repos)} repo(s)", self._repo_data(repos))

        if operation == "active":
            repo = self.manager.active_repo
            if repo is None:
                return ExecutionResult(True, "No active repository selected.", data=None)
            return ExecutionResult(
                True,
                f"Active repo: {repo.name}",
                data={"name": repo.name, "path": str(repo.path)},
            )

        if operation == "switch":
            repo = self.manager.switch(str(params["query"]))
            self.context_bus.set_active_workspace(repo.path)
            return ExecutionResult(
                True,
                f"Active repo switched to {repo.name}",
                data={"name": repo.name, "path": str(repo.path)},
            )

        return ExecutionResult(False, "unknown workspace operation", error="unknown operation")

    @staticmethod
    def _repo_data(repos) -> list[dict[str, str]]:
        return [{"name": repo.name, "path": str(Path(repo.path))} for repo in repos]
