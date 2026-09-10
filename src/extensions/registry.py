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
        metadata: ExtensionMetadata | None = None,
        *,
        replace: bool = False,
    ) -> None:
        with self._lock:
            if name in self._extensions and not replace:
                raise ValueError(f"Extension '{name}' already registered")
            if metadata is None:
                metadata = ExtensionMetadata(
                    name=name,
                    version="1.0.0",
                    category="general",
                    description=f"Extension {name}",
                    status=ExtensionStatus.REGISTERED,
                )
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

    def initialize(self, name: str) -> bool:
        """Initializes an extension by calling its initialize() method and setting status to ACTIVE."""
        ext = self.get(name)
        if ext is None:
            return False
        try:
            if hasattr(ext, "initialize") and callable(ext.initialize):
                ok = bool(ext.initialize())
                if ok:
                    self.update_status(name, ExtensionStatus.ACTIVE)
                    return True
                else:
                    self.update_status(name, ExtensionStatus.ERROR)
                    return False
            self.update_status(name, ExtensionStatus.ACTIVE)
            return True
        except Exception:
            self.update_status(name, ExtensionStatus.ERROR)
            return False

    def shutdown(self, name: str) -> bool:
        """Shuts down an extension cleanly and marks it STOPPED."""
        ext = self.get(name)
        if ext is None:
            return False
        try:
            if hasattr(ext, "shutdown") and callable(ext.shutdown):
                ext.shutdown()
            self.update_status(name, ExtensionStatus.STOPPED)
            return True
        except Exception:
            self.update_status(name, ExtensionStatus.ERROR)
            return False

    def health_check(self, name: str) -> dict[str, Any]:
        """Runs a diagnostic health check on an extension and updates status."""
        ext = self.get(name)
        meta = self.get_metadata(name)
        if ext is None or meta is None:
            return {"name": name, "status": "unknown", "healthy": False, "error": "not_found"}
        try:
            details: dict[str, Any] = {}
            is_avail = True
            if hasattr(ext, "is_available") and callable(ext.is_available):
                is_avail = bool(ext.is_available())
            if hasattr(ext, "health_check") and callable(ext.health_check):
                details = ext.health_check()
                healthy = details.get("healthy", is_avail)
            else:
                healthy = is_avail
                details = {"available": is_avail}

            if healthy:
                self.update_status(name, ExtensionStatus.ACTIVE)
            else:
                self.update_status(name, ExtensionStatus.DEGRADED)

            return {
                "name": name,
                "status": self.get_metadata(name).status.value if self.get_metadata(name) else "unknown",
                "healthy": healthy,
                "details": details,
            }
        except Exception as exc:
            self.update_status(name, ExtensionStatus.ERROR)
            return {"name": name, "status": "error", "healthy": False, "error": str(exc)}

    def recover(self, name: str) -> bool:
        """Attempts to recover a degraded or errored extension."""
        self.update_status(name, ExtensionStatus.RECOVERING)
        return self.initialize(name)

    def initialize_all(self) -> dict[str, bool]:
        """Initializes all registered extensions in registration order."""
        results = {}
        with self._lock:
            names = list(self._extensions.keys())
        for name in names:
            results[name] = self.initialize(name)
        return results

    def shutdown_all(self) -> None:
        """Shuts down all registered extensions cleanly."""
        with self._lock:
            names = list(self._extensions.keys())
        for name in names:
            self.shutdown(name)

    def is_level5_ready(self, required_extensions: list[str] | None = None) -> bool:
        """Determines if the runtime has the core Level 5 extension modules registered and active."""
        reqs = required_extensions or ["mcp", "scheduler", "multi_agent"]
        with self._lock:
            for req in reqs:
                if req not in self._extensions:
                    return False
                meta = self._metadata.get(req)
                if not meta or meta.status not in (
                    ExtensionStatus.ACTIVE,
                    ExtensionStatus.INITIALIZED,
                ):
                    return False
            return True
