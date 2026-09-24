from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class ToolResult:
    success: bool
    data: Any = None
    error: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    handler: Callable[[dict[str, Any]], ToolResult]
    tags: set[str] = field(default_factory=set)
    risk: str = "low"

    def call(self, params: dict[str, Any] | None = None) -> ToolResult:
        try:
            return self.handler(params or {})
        except Exception as exc:
            return ToolResult(False, error=f"{type(exc).__name__}: {exc}")


class ToolRegistry:
    """Capability registry inspired by tool routers such as treg."""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name]

    def search(self, query: str) -> list[dict[str, Any]]:
        words = set(query.lower().split())
        ranked = []
        for tool in self._tools.values():
            haystack = f"{tool.name} {tool.description} {' '.join(tool.tags)}".lower()
            score = sum(word in haystack for word in words)
            if score:
                ranked.append((score, tool))
        ranked.sort(key=lambda item: (-item[0], item[1].name))
        return [self.describe(t.name) for _, t in ranked]

    def describe(self, name: str) -> dict[str, Any]:
        tool = self.get(name)
        return {"name": tool.name, "description": tool.description, "tags": sorted(tool.tags), "risk": tool.risk}

    def catalog(self) -> list[dict[str, Any]]:
        return [self.describe(name) for name in sorted(self._tools)]

    def call(self, name: str, params: dict[str, Any] | None = None) -> ToolResult:
        return self.get(name).call(params)


def _workspace_root(params: dict[str, Any]) -> Path:
    return Path(params.get("workspace", ".nexa/workspace")).resolve()


def _read_file(params: dict[str, Any]) -> ToolResult:
    root = _workspace_root(params)
    path = (root / str(params["path"])).resolve()
    if root not in path.parents and path != root:
        return ToolResult(False, error="path escapes workspace")
    return ToolResult(True, {"path": str(path), "content": path.read_text(encoding="utf-8")})


def _write_file(params: dict[str, Any]) -> ToolResult:
    root = _workspace_root(params)
    root.mkdir(parents=True, exist_ok=True)
    path = (root / str(params["path"])).resolve()
    if root not in path.parents and path != root:
        return ToolResult(False, error="path escapes workspace")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(params.get("content", "")), encoding="utf-8")
    return ToolResult(True, {"path": str(path)})


def _cli(params: dict[str, Any]) -> ToolResult:
    argv = params.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(x, str) for x in argv):
        return ToolResult(False, error="argv must be a non-empty string array")
    timeout = min(max(int(params.get("timeout", 30)), 1), 120)
    completed = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, shell=False)
    return ToolResult(completed.returncode == 0, {
        "argv": argv, "returncode": completed.returncode,
        "stdout": completed.stdout[-20000:], "stderr": completed.stderr[-20000:]
    }, None if completed.returncode == 0 else f"command exited {completed.returncode}")


def _json_tool(params: dict[str, Any]) -> ToolResult:
    return ToolResult(True, json.loads(str(params.get("json", "{}"))))


def build_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(Tool("workspace.read", "Read a UTF-8 file from the NEXA workspace", _read_file, {"file", "workspace", "read"}))
    registry.register(Tool("workspace.write", "Write a UTF-8 artifact inside the NEXA workspace", _write_file, {"file", "workspace", "write", "artifact"}, "medium"))
    registry.register(Tool("cli.run", "Run an argv-based CLI command and return structured output", _cli, {"cli", "terminal", "command", "harness"}, "high"))
    registry.register(Tool("data.json", "Parse JSON into structured agent data", _json_tool, {"json", "data", "parse"}))
    return registry
