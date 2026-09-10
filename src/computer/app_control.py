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
        # Direct name match
        if q in self._apps:
            return self._apps[q]
        # Alias match
        if q in self._aliases:
            return self._apps.get(self._aliases[q])
        # Fuzzy: check if query is substring of any app name
        for name, app in self._apps.items():
            if q in name or any(q in alias.lower() for alias in app.aliases):
                return app
        return None
    
    def list_apps(self) -> list[AppInfo]:
        """List all registered apps."""
        return sorted(self._apps.values(), key=lambda a: a.name)
    
    def _register_defaults(self) -> None:
        """Register well-known Windows applications."""
        defaults = [
            AppInfo("Chrome", "chrome", ("google chrome", "browser"), "browser"),
            AppInfo("Edge", "msedge", ("microsoft edge",), "browser"),
            AppInfo("Firefox", "firefox", (), "browser"),
            AppInfo("VS Code", "code", ("vscode", "visual studio code"), "editor"),
            AppInfo("Notepad", "notepad", ("notepad.exe",), "editor"),
            AppInfo("Notepad++", "notepad++", ("npp",), "editor"),
            AppInfo("File Explorer", "explorer", ("explorer.exe", "files"), "system"),
            AppInfo("Terminal", "wt", ("windows terminal",), "terminal"),
            AppInfo("PowerShell", "powershell", ("pwsh", "ps"), "terminal"),
            AppInfo("Command Prompt", "cmd", ("cmd.exe", "command prompt"), "terminal"),
            AppInfo("Task Manager", "taskmgr", ("task manager",), "system"),
            AppInfo("Settings", "ms-settings:", ("windows settings",), "system"),
            AppInfo("Calculator", "calc", ("calculator",), "utility"),
            AppInfo("Paint", "mspaint", ("paint",), "utility"),
            AppInfo("Spotify", "spotify", (), "media"),
        ]
        for app in defaults:
            self.register(app)


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
            cmd = [app.executable] + list(args)
            # Use shell=True for ms-settings: protocol and similar
            if app.executable.startswith("ms-") or "://" in app.executable:
                subprocess.Popen(["start", "", app.executable], shell=True)
            else:
                subprocess.Popen(cmd, shell=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
