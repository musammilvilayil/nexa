from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Mapping

from core import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata


_READ_RE = re.compile(r"^(?:/file\s+read|file\s+read)\s+(.+)$", re.IGNORECASE)
_LIST_RE = re.compile(r"^(?:/file\s+list|file\s+list)(?:\s+(.+))?$", re.IGNORECASE)
_WRITE_RE = re.compile(r"^(?:/file\s+write|file\s+write)\s+(.+?)\s+::\s+(.*)$", re.IGNORECASE | re.DOTALL)
_PATCH_RE = re.compile(
    r"^(?:/file\s+patch|file\s+patch)\s+(.+?)\s+::\s+(.*?)\s+=>\s+(.*)$",
    re.IGNORECASE | re.DOTALL,
)


class FileSkill:
    """UTF-8 file operations confined to the active workspace path."""

    def __init__(self, *, max_read_bytes: int = 1_000_000, max_write_bytes: int = 1_000_000) -> None:
        if max_read_bytes <= 0 or max_write_bytes <= 0:
            raise ValueError("file limits must be positive")
        self.max_read_bytes = int(max_read_bytes)
        self.max_write_bytes = int(max_write_bytes)
        self.metadata = SkillMetadata(
            name="files",
            version="0.1.0",
            description="Contained UTF-8 file read/list/write/patch operations for the active workspace",
            operations=(
                OperationSpec("read", "Read a UTF-8 file", RiskTier.READ),
                OperationSpec("list", "List files under a workspace-relative directory", RiskTier.READ),
                OperationSpec("write", "Create or replace a UTF-8 file", RiskTier.MUTATE),
                OperationSpec("patch", "Replace one exact text occurrence", RiskTier.MUTATE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = text.strip()
        match = _READ_RE.fullmatch(normalized)
        if match:
            return SkillMatch("files", "read", {"path": match.group(1).strip()})
        match = _LIST_RE.fullmatch(normalized)
        if match:
            return SkillMatch("files", "list", {"path": (match.group(1) or ".").strip()})
        match = _WRITE_RE.fullmatch(normalized)
        if match:
            return SkillMatch("files", "write", {"path": match.group(1).strip(), "content": match.group(2)})
        match = _PATCH_RE.fullmatch(normalized)
        if match:
            return SkillMatch(
                "files",
                "patch",
                {"path": match.group(1).strip(), "old": match.group(2), "new": match.group(3)},
            )
        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        root = self._root(context)
        if operation == "list":
            path = self._resolve(root, str(params.get("path", ".")), allow_root=True)
            return {"root": root, "path": path}
        if operation == "read":
            path = self._resolve(root, str(params.get("path", "")))
            return {"root": root, "path": path}
        if operation == "write":
            path = self._resolve(root, str(params.get("path", "")))
            content = str(params.get("content", ""))
            if len(content.encode("utf-8")) > self.max_write_bytes:
                raise ValueError("file content exceeds write limit")
            return {"root": root, "path": path, "content": content}
        if operation == "patch":
            path = self._resolve(root, str(params.get("path", "")))
            old = str(params.get("old", ""))
            new = str(params.get("new", ""))
            if not old:
                raise ValueError("patch old text cannot be empty")
            if len(new.encode("utf-8")) > self.max_write_bytes:
                raise ValueError("replacement text exceeds write limit")
            return {"root": root, "path": path, "old": old, "new": new}
        raise ValueError("unknown file operation")

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        path: Path = params["path"]
        root: Path = params["root"]

        if operation == "list":
            if not path.exists() or not path.is_dir():
                return ExecutionResult(False, "directory not found", error="directory not found")
            entries: list[dict[str, Any]] = []
            for current, dirnames, filenames in os.walk(path):
                current_path = Path(current)
                dirnames[:] = [name for name in dirnames if name not in {".git", ".venv", "venv", "node_modules", "__pycache__"}]
                for name in sorted(filenames):
                    candidate = (current_path / name).resolve()
                    if not candidate.is_relative_to(root):
                        continue
                    entries.append({
                        "path": candidate.relative_to(root).as_posix(),
                        "size": candidate.stat().st_size,
                    })
                    if len(entries) >= 1000:
                        return ExecutionResult(True, "File list truncated at 1000 entries", entries)
            return ExecutionResult(True, f"Found {len(entries)} file(s)", entries)

        if operation == "read":
            if not path.exists() or not path.is_file():
                return ExecutionResult(False, "file not found", error="file not found")
            size = path.stat().st_size
            if size > self.max_read_bytes:
                return ExecutionResult(False, "file exceeds read limit", error="file too large")
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return ExecutionResult(False, "file is not valid UTF-8", error="invalid utf-8")
            return ExecutionResult(True, f"Read {path.relative_to(root).as_posix()}", data=content)

        if operation == "write":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(str(params["content"]), encoding="utf-8")
            return ExecutionResult(True, f"Wrote {path.relative_to(root).as_posix()}")

        if operation == "patch":
            if not path.exists() or not path.is_file():
                return ExecutionResult(False, "file not found", error="file not found")
            if path.stat().st_size > self.max_read_bytes:
                return ExecutionResult(False, "file exceeds read limit", error="file too large")
            content = path.read_text(encoding="utf-8")
            old = str(params["old"])
            count = content.count(old)
            if count != 1:
                return ExecutionResult(
                    False,
                    f"patch requires exactly one match; found {count}",
                    error="ambiguous patch target",
                )
            updated = content.replace(old, str(params["new"]), 1)
            if len(updated.encode("utf-8")) > self.max_write_bytes:
                return ExecutionResult(False, "patched file exceeds write limit", error="file too large")
            path.write_text(updated, encoding="utf-8")
            return ExecutionResult(True, f"Patched {path.relative_to(root).as_posix()}")

        return ExecutionResult(False, "unknown file operation", error="unknown operation")

    @staticmethod
    def _root(context: Mapping[str, Any]) -> Path:
        raw = context.get("active_workspace_path")
        if not raw:
            raise ValueError("no active workspace selected")
        root = Path(str(raw)).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError("active workspace does not exist")
        return root

    @staticmethod
    def _resolve(root: Path, raw: str, *, allow_root: bool = False) -> Path:
        value = raw.strip()
        if not value:
            raise ValueError("file path required")
        relative = Path(value)
        if relative.is_absolute() or ".." in relative.parts or "\x00" in value:
            raise ValueError("path must stay inside active workspace")
        target = (root / relative).resolve()
        if not target.is_relative_to(root):
            raise ValueError("path escaped active workspace")
        if not allow_root and target == root:
            raise ValueError("file path cannot be workspace root")
        return target
