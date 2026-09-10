from __future__ import annotations

import threading
from typing import Any

from .contracts import ExtensionMetadata, ExtensionStatus


class ExtensionRegistry:
    """Manages pluggable external service integrations and Level 5 autonomous capabilities."""

    def __init__(self) -> None:
        self._extensions: dict[str, Any] = {}
        self._metadata: dict[str, ExtensionMetadata] = {}
        self._lock = threading.Lock()

    def register(
        self,
        name: str,
        extension: Any,
        metadata: ExtensionMetadata,
        *,
        replace: bool = False,
    ) -> None:
        with self._lock:
            if name in self._extensions and not replace:
                raise ValueError(f"Extension '{name}' already registered")
            self._extensions[name] = extension
            self._metadata[name] = metadata

    def get(self, name: str) -> Any | None:
        with self._lock:
            return self._extensions.get(name)

    def get_metadata(self, name: str) -> ExtensionMetadata | None:
        with self._lock:
            return self._metadata.get(name)

    def has(self, name: str) -> bool:
        with self._lock:
            return name in self._extensions

    def unregister(self, name: str) -> bool:
        with self._lock:
            if name in self._extensions:
                del self._extensions[name]
                self._metadata.pop(name, None)
                return True
            return False

    def list_extensions(self, category: str | None = None) -> list[ExtensionMetadata]:
        with self._lock:
            if category:
                return [m for m in self._metadata.values() if m.category == category]
            return list(self._metadata.values())

    def update_status(self, name: str, status: ExtensionStatus) -> bool:
        with self._lock:
            if name in self._metadata:
                old = self._metadata[name]
                self._metadata[name] = ExtensionMetadata(
                    name=old.name,
                    version=old.version,
                    category=old.category,
                    description=old.description,
                    auth_required=old.auth_required,
                    status=status,
                    supported_operations=old.supported_operations,
                    extra=old.extra,
                )
                return True
            return False

    def is_level5_ready(self, required_extensions: list[str] | None = None) -> bool:
        """Determines if the runtime has the core Level 5 extension modules registered and active."""
        reqs = required_extensions or ["mcp", "scheduler", "multi_agent"]
        with self._lock:
            for req in reqs:
                if req not in self._extensions:
                    return False
                meta = self._metadata.get(req)
                if not meta or meta.status not in (ExtensionStatus.ACTIVE, ExtensionStatus.INITIALIZED):
                    return False
            return True
