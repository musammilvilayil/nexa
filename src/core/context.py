from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class ContextSnapshot:
    active_workspace_path: str | None
    session: Mapping[str, Any]
    environment_flags: Mapping[str, Any]

    def as_mapping(self) -> dict[str, Any]:
        return {
            "active_workspace_path": self.active_workspace_path,
            "session": dict(self.session),
            "environment_flags": dict(self.environment_flags),
        }


class ContextBus:
    """Owns runtime state shared across the standalone kernel.

    This is intentionally capability-agnostic. It stores state only; it does not
    know what Git, files, browsers, models, or APIs are.
    """

    def __init__(self) -> None:
        self._active_workspace_path: str | None = None
        self._session: dict[str, Any] = {}
        self._environment_flags: dict[str, Any] = {}

    def set_active_workspace(self, path: str | Path | None) -> None:
        if path is None:
            self._active_workspace_path = None
            return
        self._active_workspace_path = str(Path(path).expanduser().resolve())

    def set_session_value(self, key: str, value: Any) -> None:
        self._session[key] = value

    def set_environment_flag(self, key: str, value: Any) -> None:
        self._environment_flags[key] = value

    def snapshot(self) -> ContextSnapshot:
        return ContextSnapshot(
            active_workspace_path=self._active_workspace_path,
            session=dict(self._session),
            environment_flags=dict(self._environment_flags),
        )
