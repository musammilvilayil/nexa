from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
}


class WorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class RepoInfo:
    name: str
    path: Path


class WorkspaceManager:
    """Discover and select local Git repositories inside configured roots.

    WorkspaceManager never executes Git or shell commands. It owns only the
    repository-context boundary used by future FileSkill/GitSkill operations.
    All active repositories must be discovered beneath an explicitly configured
    workspace root.
    """

    def __init__(
        self,
        roots: Iterable[str | Path],
        *,
        ignored_dirs: Iterable[str] = DEFAULT_IGNORED_DIRS,
    ):
        resolved_roots: list[Path] = []
        for raw_root in roots:
            root = Path(raw_root).expanduser().resolve()
            if not root.exists() or not root.is_dir():
                raise WorkspaceError(f"Workspace root does not exist: {root}")
            if root not in resolved_roots:
                resolved_roots.append(root)

        if not resolved_roots:
            raise WorkspaceError("At least one workspace root is required")

        self.roots = tuple(resolved_roots)
        self.ignored_dirs = frozenset(ignored_dirs)
        self._repos: tuple[RepoInfo, ...] = ()
        self._active_repo: RepoInfo | None = None

    @property
    def repositories(self) -> tuple[RepoInfo, ...]:
        return self._repos

    @property
    def active_repo(self) -> RepoInfo | None:
        return self._active_repo

    def require_active_repo(self) -> RepoInfo:
        if self._active_repo is None:
            raise WorkspaceError("No active repository selected")
        return self._active_repo

    def discover(self) -> tuple[RepoInfo, ...]:
        found: dict[Path, RepoInfo] = {}

        for root in self.roots:
            # If the configured root itself is a repository, include it and do
            # not recursively treat folders inside that repository as peers.
            if self._is_git_repo(root):
                found[root] = RepoInfo(name=root.name, path=root)
                continue

            for current, dirnames, filenames in os.walk(root):
                current_path = Path(current).resolve()

                # Never traverse common generated/dependency directories.
                dirnames[:] = [
                    name
                    for name in dirnames
                    if name not in self.ignored_dirs and not name.startswith(".git")
                ]

                # Worktrees can expose .git as a file; normal repositories use
                # a .git directory. Support both forms.
                has_git_dir = (current_path / ".git").is_dir()
                has_git_file = ".git" in filenames and (current_path / ".git").is_file()
                if has_git_dir or has_git_file:
                    if self._inside_configured_root(current_path):
                        found[current_path] = RepoInfo(
                            name=current_path.name,
                            path=current_path,
                        )
                    # A repository is one workspace unit. Do not scan into it
                    # looking for nested repositories by accident.
                    dirnames[:] = []

        self._repos = tuple(
            sorted(found.values(), key=lambda repo: (repo.name.casefold(), str(repo.path).casefold()))
        )

        if self._active_repo is not None:
            by_path = {repo.path: repo for repo in self._repos}
            self._active_repo = by_path.get(self._active_repo.path)

        return self._repos

    def switch(self, query: str) -> RepoInfo:
        query = query.strip()
        if not query:
            raise WorkspaceError("Repository name cannot be empty")

        if not self._repos:
            self.discover()

        # Exact path selection is allowed only when that exact repository was
        # discovered inside a configured workspace root.
        path_candidate = Path(query).expanduser()
        if path_candidate.is_absolute():
            resolved = path_candidate.resolve()
            matches = [repo for repo in self._repos if repo.path == resolved]
        else:
            folded = query.casefold()
            matches = [repo for repo in self._repos if repo.name.casefold() == folded]

        if not matches:
            raise WorkspaceError(f"Repository not found in workspace: {query}")
        if len(matches) > 1:
            locations = ", ".join(str(repo.path) for repo in matches)
            raise WorkspaceError(f"Repository name is ambiguous: {query}. Matches: {locations}")

        self._active_repo = matches[0]
        return self._active_repo

    def clear_active(self) -> None:
        self._active_repo = None

    def _inside_configured_root(self, candidate: Path) -> bool:
        candidate = candidate.resolve()
        return any(candidate == root or candidate.is_relative_to(root) for root in self.roots)

    @staticmethod
    def _is_git_repo(path: Path) -> bool:
        marker = path / ".git"
        return marker.is_dir() or marker.is_file()
