from __future__ import annotations

import os
import sys
from pathlib import Path

REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
REG_VALUE_NAME = "NEXA_OS"


def get_default_command() -> str:
    """Returns the default python launcher command for auto-starting NEXA."""
    repo_root = Path(__file__).resolve().parents[2]
    launcher = repo_root / "src" / "ui" / "launcher.py"
    venv_py = repo_root / ".venv" / "Scripts" / "pythonw.exe"
    if not venv_py.exists():
        venv_py = repo_root / ".venv" / "Scripts" / "python.exe"
    if not venv_py.exists():
        venv_py = Path(sys.executable)

    return f'"{venv_py}" "{launcher}" --background'


def is_autostart_enabled() -> bool:
    """Checks if NEXA is configured to run at Windows login."""
    if sys.platform != "win32":
        return False

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ) as key:
            try:
                val, _ = winreg.QueryValueEx(key, REG_VALUE_NAME)
                return bool(val)
            except FileNotFoundError:
                return False
    except Exception:
        return False


def get_autostart_command() -> str | None:
    """Gets the currently configured auto-start command string, if any."""
    if sys.platform != "win32":
        return None

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ) as key:
            try:
                val, _ = winreg.QueryValueEx(key, REG_VALUE_NAME)
                return str(val)
            except FileNotFoundError:
                return None
    except Exception:
        return None


def enable_autostart(command: str | None = None) -> bool:
    """Enables NEXA auto-start in the Windows registry."""
    if sys.platform != "win32":
        return False

    cmd = command or get_default_command()

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, REG_VALUE_NAME, 0, winreg.REG_SZ, cmd)
            return True
    except Exception:
        return False


def disable_autostart() -> bool:
    """Disables NEXA auto-start from the Windows registry."""
    if sys.platform != "win32":
        return False

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
            try:
                winreg.DeleteValue(key, REG_VALUE_NAME)
            except FileNotFoundError:
                pass
            return True
    except Exception:
        return False
