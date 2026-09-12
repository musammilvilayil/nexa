from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Canonical application alias mapping
APP_ALIASES: dict[str, str] = {
    "notepad": "notepad",
    "notebook": "notepad",
    "note": "notepad",
    "notes": "notepad",
    "text editor": "notepad",
    "editor": "notepad",
    "notepad++": "notepad",
    "calc": "calculator",
    "calculator": "calculator",
    "calculator app": "calculator",
    "chrome": "chrome",
    "google chrome": "chrome",
    "browser": "chrome",
    "web browser": "chrome",
    "edge": "edge",
    "microsoft edge": "edge",
    "msedge": "edge",
    "firefox": "firefox",
    "mozilla firefox": "firefox",
    "explorer": "explorer",
    "file explorer": "explorer",
    "file manager": "explorer",
    "files": "explorer",
    "terminal": "terminal",
    "cmd": "terminal",
    "command prompt": "terminal",
    "powershell": "terminal",
    "paint": "paint",
    "mspaint": "paint",
    "code": "code",
    "vscode": "code",
    "vs code": "code",
}

# Standard directory aliases
PATH_ALIASES: dict[str, Path] = {
    "downloads": Path.home() / "Downloads",
    "download": Path.home() / "Downloads",
    "documents": Path.home() / "Documents",
    "document": Path.home() / "Documents",
    "desktop": Path.home() / "Desktop",
}

_POLITE_PREFIX_RE = re.compile(
    r"^(?:can\s+you\s+(?:please\s+)?|could\s+you\s+(?:please\s+)?|would\s+you\s+(?:please\s+)?|"
    r"please\s+|kindly\s+|i\s+want\s+you\s+to\s+|help\s+me\s+(?:to\s+)?|dayavayi\s+|onnu\s+)",
    re.IGNORECASE,
)

_POLITE_SUFFIX_RE = re.compile(
    r"\s+(?:please|for\s+me|dayavayi|onnu)$",
    re.IGNORECASE,
)


class EntityResolver:
    """Resolves natural language entities (apps, paths, commands) into canonical representations."""

    @staticmethod
    def strip_politeness(text: str) -> str:
        """Strip conversational pleasantries, polite prefixes and suffixes."""
        cleaned = text.strip()
        cleaned = _POLITE_PREFIX_RE.sub("", cleaned).strip()
        cleaned = _POLITE_SUFFIX_RE.sub("", cleaned).strip()
        return cleaned

    @staticmethod
    def resolve_app_name(raw_name: str) -> str:
        """Map common user terms and aliases to canonical application name."""
        clean = raw_name.lower().strip()
        if clean.startswith("the "):
            clean = clean[4:].strip()
        if clean.endswith(".exe"):
            clean = clean[:-4].strip()
        if clean.endswith(" application"):
            clean = clean[:-12].strip()
        if clean.endswith(" app"):
            clean = clean[:-4].strip()
        return APP_ALIASES.get(clean, clean)

    @staticmethod
    def resolve_path(raw_path: str, default_root: Path | None = None) -> Path:
        """Resolve a file or folder path string, handling aliases, quotes, and expansion."""
        clean = raw_path.strip().strip("'\"")
        lower = clean.lower()

        if lower in PATH_ALIASES:
            return PATH_ALIASES[lower].resolve()

        p = Path(clean).expanduser()
        if p.is_absolute():
            return p.resolve()

        root = default_root or Path.cwd()
        return (root / p).resolve()

    @staticmethod
    def normalize_command(text: str) -> str:
        """Produce a normalized canonical version of natural language input."""
        stripped = EntityResolver.strip_politeness(text).rstrip(".!?")
        
        # Check Malayalam / Manglish verb patterns
        # 1. <app/thing> thurakku / thuru / open cheyy
        m_open = re.match(r"^(.+?)\s+(?:thurakku|thuru|open\s+cheyy)$", stripped, re.IGNORECASE)
        if m_open:
            app_raw = m_open.group(1).strip()
            canonical_app = EntityResolver.resolve_app_name(app_raw)
            return f"open {canonical_app}"

        # 2. <app/thing> adakku / close cheyy
        m_close = re.match(r"^(.+?)\s+(?:adakku|adakk|close\s+cheyy)$", stripped, re.IGNORECASE)
        if m_close:
            app_raw = m_close.group(1).strip()
            canonical_app = EntityResolver.resolve_app_name(app_raw)
            return f"close {canonical_app}"

        # 3. <text> type cheyy
        m_type = re.match(r"^(.+?)\s+type\s+cheyy$", stripped, re.IGNORECASE)
        if m_type:
            return f"type \"{m_type.group(1).strip()}\""

        # 4. <file> save cheyy
        m_save = re.match(r"^(.+?)\s+save\s+cheyy$", stripped, re.IGNORECASE)
        if m_save:
            return f"save file as: {m_save.group(1).strip()}"

        # 5. google il <query> search cheyy / search for <query>
        m_search = re.match(r"^(?:google\s+il\s+)?(.+?)\s+search\s+cheyy$", stripped, re.IGNORECASE)
        if m_search:
            return f"search Google for {m_search.group(1).strip()}"

        # 6. 'open notebook' -> 'open notepad'
        m_open_eng = re.match(r"^(?:open|launch|start)\s+(.+)$", stripped, re.IGNORECASE)
        if m_open_eng:
            app_candidate = m_open_eng.group(1).strip()
            # If it's a URL, keep as URL
            if "." in app_candidate and not app_candidate.endswith(".exe") and ("http" in app_candidate or "www" in app_candidate or ".com" in app_candidate or ".org" in app_candidate):
                return stripped
            canonical_app = EntityResolver.resolve_app_name(app_candidate)
            return f"open {canonical_app}"

        return stripped
