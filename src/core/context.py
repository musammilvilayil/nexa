from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


@dataclass
class DeviceContext:
    """Safe, non-secret state of active computer and application environment."""
    active_window: str = ""
    active_application: str = ""
    active_browser_tab: str = ""
    active_browser_url: str = ""
    current_workspace: str = ""
    last_selected_file: str = ""
    last_action_target: str = ""
    last_action_result: str = ""
    current_task_id: str = ""
    updated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def update_from_window(self, title: str, process_name: str) -> None:
        """Update active window and application safely."""
        self.active_window = title
        self.active_application = process_name
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def update_last_file(self, file_path: str) -> None:
        """Update last touched or selected file."""
        self.last_selected_file = file_path
        self.last_action_target = file_path
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def resolve_reference(self, user_text: str) -> str:
        """Resolve deictic / contextual references like 'ith', 'ath', 'ee file', 'last file'."""
        text = user_text.strip()
        text_lower = text.lower()

        # 1. Malayalam/Manglish 'ith' / 'ath' references
        # e.g. "ith close cheyy", "ath close cheyy" -> "close <active_application>"
        if "close" in text_lower and ("ith" in text_lower or "ath" in text_lower):
            target = self.active_application or self.active_window or "current window"
            # Strip trailing .exe for natural app close
            if target.lower().endswith(".exe"):
                target = target[:-4]
            return f"close {target}"

        # e.g. "ith open cheyy" / "ath open cheyy" -> refer to last file or app
        if "open" in text_lower and ("ith" in text_lower or "ath" in text_lower):
            if self.last_selected_file:
                return f"open {self.last_selected_file}"
            if self.last_action_target:
                return f"open {self.last_action_target}"

        # 2. "ee file" / "this file" / "last file"
        if ("ee file" in text_lower or "this file" in text_lower or "last file" in text_lower):
            if self.last_selected_file:
                # Replace the phrase with the actual path
                replaced = re.sub(r"\b(ee\s+file|this\s+file|last\s+file)\b", self.last_selected_file, text, flags=re.IGNORECASE)
                return replaced

        # 3. "last result"
        if "last result" in text_lower and self.last_action_result:
            return text.replace("last result", self.last_action_result)

        # 4. "avide" (there)
        if "avide" in text_lower and self.last_action_target:
            return text.replace("avide", self.last_action_target)

        return user_text


# Global device context singleton
CURRENT_DEVICE_CONTEXT = DeviceContext()
