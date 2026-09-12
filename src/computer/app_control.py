from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppInfo:
    """Information about a registered application."""
    name: str
    executable: str  # Full path or command name
    aliases: tuple[str, ...] = ()
    category: str = "general"  # general, browser, editor, terminal, media, etc.
    is_discovered: bool = False  # True if auto-discovered, False if manually registered


class ApplicationRegistry:
    """Registry of known applications.
    
    Supports manual registration and auto-discovery of common Windows apps.
    Lookup is case-insensitive and supports aliases.
    """
    
    def __init__(self) -> None:
        self._apps: dict[str, AppInfo] = {}  # lowercase name -> AppInfo
        self._aliases: dict[str, str] = {}  # lowercase alias -> lowercase name
        self._register_defaults()
    
    def register(self, app: AppInfo) -> None:
        """Register an application."""
        key = app.name.lower()
        self._apps[key] = app
        for alias in app.aliases:
            self._aliases[alias.lower()] = key
    
    def find(self, query: str) -> AppInfo | None:
        """Find an app by name or alias (case-insensitive)."""
        q = query.strip().lower()
        if not q:
            return None
        # Direct name match
        if q in self._apps:
            return self._apps[q]
        # Alias match
        if q in self._aliases:
            return self._apps.get(self._aliases[q])

        # Strip common leading prefixes: "the ", "my ", "windows "
        for prefix in ("the ", "my ", "windows "):
            if q.startswith(prefix) and len(q) > len(prefix):
                q_sub = q[len(prefix):].strip()
                if q_sub in self._apps:
                    return self._apps[q_sub]
                if q_sub in self._aliases:
                    return self._apps.get(self._aliases[q_sub])

        # Strip common trailing suffixes: " app", " application", " editor"
        for suffix in (" app", " application", " editor"):
            if q.endswith(suffix) and len(q) > len(suffix):
                q_sub = q[:-len(suffix)].strip()
                if q_sub in self._apps:
                    return self._apps[q_sub]
                if q_sub in self._aliases:
                    return self._apps.get(self._aliases[q_sub])

        # Substring / fuzzy match
        for name, app in self._apps.items():
            if q in name or any(q == alias.lower() or q in alias.lower() for alias in app.aliases):
                return app
        return None
    
    def list_apps(self) -> list[AppInfo]:
        """List all registered apps."""
        return sorted(self._apps.values(), key=lambda a: a.name)
    
    def _register_defaults(self) -> None:
        """Register well-known Windows applications with comprehensive aliases."""
        defaults = [
            AppInfo("Chrome", "chrome", ("google chrome", "browser", "web browser", "google browser", "internet"), "browser"),
            AppInfo("Edge", "msedge", ("microsoft edge", "edge browser"), "browser"),
            AppInfo("Firefox", "firefox", ("mozilla firefox",), "browser"),
            AppInfo("VS Code", "code", ("vscode", "visual studio code", "code editor"), "editor"),
            AppInfo("Notepad", "notepad", ("notepad.exe", "notebook", "text editor", "text editor app", "notes", "note"), "editor"),
            AppInfo("Notepad++", "notepad++", ("npp",), "editor"),
            AppInfo("File Explorer", "explorer", ("explorer.exe", "files", "file manager", "my computer", "this pc"), "system"),
            AppInfo("Terminal", "wt", ("windows terminal",), "terminal"),
            AppInfo("PowerShell", "powershell", ("pwsh", "ps"), "terminal"),
            AppInfo("Command Prompt", "cmd", ("cmd.exe", "command prompt", "terminal window"), "terminal"),
            AppInfo("Task Manager", "taskmgr", ("task manager",), "system"),
            AppInfo("Settings", "ms-settings:", ("windows settings",), "system"),
            AppInfo("Calculator", "calc", ("calculator", "calc", "windows calculator", "calculator app", "calc.exe"), "utility"),
            AppInfo("Paint", "mspaint", ("paint", "mspaint.exe", "drawing"), "utility"),
            AppInfo("Spotify", "spotify", (), "media"),
        ]
        for app in defaults:
            self.register(app)


def resolve_executable(executable: str) -> str:
    """Resolves an executable name to its full path if needed on Windows."""
    import shutil
    if os.path.isabs(executable) and os.path.isfile(executable):
        return executable

    which_path = shutil.which(executable)
    if which_path:
        return which_path

    name_lower = executable.lower().replace(".exe", "")
    known_paths = {
        "chrome": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ],
        "msedge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
        ],
        "firefox": [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
        ],
        "code": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
            r"C:\Program Files\Microsoft VS Code\Code.exe",
        ],
        "notepad": [
            r"C:\Windows\System32\notepad.exe",
            r"C:\Windows\notepad.exe",
        ],
        "calc": [
            r"C:\Windows\System32\calc.exe",
        ],
        "mspaint": [
            r"C:\Windows\System32\mspaint.exe",
        ],
        "taskmgr": [
            r"C:\Windows\System32\Taskmgr.exe",
        ],
    }
    if name_lower in known_paths:
        for p in known_paths[name_lower]:
            if os.path.isfile(p):
                return p

    return executable


class ApplicationLauncher:
    """Launch and manage applications.
    
    Uses subprocess to launch apps. Checks if apps are running via tasklist.
    """
    
    def __init__(self, registry: ApplicationRegistry | None = None) -> None:
        self._registry = registry or ApplicationRegistry()
    
    @property
    def registry(self) -> ApplicationRegistry:
        return self._registry
    
    def launch(self, app_name: str, *, args: tuple[str, ...] = ()) -> dict[str, Any]:
        """Launch an application by name.
        
        Returns dict with 'success', 'message', 'app' keys.
        """
        app = self._registry.find(app_name)
        if app is None:
            return {
                "success": False,
                "message": f"Application '{app_name}' not found in registry",
                "app": None,
            }
        
        try:
            exe_path = resolve_executable(app.executable)
            cmd = [exe_path] + list(args)
            # Use shell=True for ms-settings: protocol and similar
            if app.executable.startswith("ms-") or "://" in app.executable:
                subprocess.Popen(["start", "", app.executable], shell=True)
            else:
                try:
                    subprocess.Popen(cmd, shell=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except FileNotFoundError:
                    # Fallback to shell start
                    subprocess.Popen(["start", "", app.executable] + list(args), shell=True)
            return {
                "success": True,
                "message": f"Launched {app.name}",
                "app": app,
            }
        except FileNotFoundError:
            return {
                "success": False,
                "message": f"Executable not found: {app.executable}",
                "app": app,
            }
        except Exception as exc:
            return {
                "success": False,
                "message": f"Failed to launch {app.name}: {exc}",
                "app": app,
            }
    
    def is_running(self, app_name: str) -> bool:
        """Check if an application is currently running."""
        app = self._registry.find(app_name)
        if app is None:
            return False
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {os.path.basename(app.executable)}*"],
                capture_output=True, text=True, timeout=5,
            )
            return app.executable.lower() in result.stdout.lower()
        except Exception:
            return False
