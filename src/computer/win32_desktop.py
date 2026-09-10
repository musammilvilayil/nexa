from __future__ import annotations

import sys
import ctypes
from typing import Any

_DESKTOP_ATTACHED = False


def ensure_desktop_attached() -> bool:
    """Ensure current thread is attached to the active interactive desktop (Default).
    
    This is necessary when running under background worker threads, services,
    or sandboxed subprocess desktops on Windows.
    """
    global _DESKTOP_ATTACHED
    if sys.platform != "win32":
        return False

    try:
        user32 = ctypes.windll.user32
        
        # Try OpenInputDesktop first
        hdesk = user32.OpenInputDesktop(0, False, 0x01FF)
        if not hdesk:
            # Fallback to OpenDesktopW('Default')
            hdesk = user32.OpenDesktopW("Default", 0, False, 0x01FF)
            
        if hdesk:
            success = bool(user32.SetThreadDesktop(hdesk))
            if success:
                _DESKTOP_ATTACHED = True
            return success
        return False
    except Exception:
        return False


def get_desktop_session_info() -> dict[str, Any]:
    """Retrieve detailed diagnostic information about the Windows desktop session."""
    if sys.platform != "win32":
        return {
            "interactive": False,
            "station": "non-windows",
            "desktop": "non-windows",
            "screen_width": 0,
            "screen_height": 0,
            "monitors": 0,
        }

    ensure_desktop_attached()
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32

        # Station name
        hwinsta = user32.GetProcessWindowStation()
        station_name_buf = ctypes.create_unicode_buffer(256)
        user32.GetUserObjectInformationW(hwinsta, 2, station_name_buf, 256, None)
        station_name = station_name_buf.value

        # Desktop name
        hdesk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
        desk_name_buf = ctypes.create_unicode_buffer(256)
        user32.GetUserObjectInformationW(hdesk, 2, desk_name_buf, 256, None)
        desk_name = desk_name_buf.value

        width = user32.GetSystemMetrics(0)   # SM_CXSCREEN
        height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
        monitors = user32.GetSystemMetrics(80) # SM_CMONITORS
        if monitors == 0:
            monitors = 1

        is_interactive = "WinSta0" in station_name

        return {
            "interactive": is_interactive,
            "station": station_name,
            "desktop": desk_name,
            "screen_width": width,
            "screen_height": height,
            "monitors": monitors,
        }
    except Exception as exc:
        return {
            "interactive": False,
            "station": "unknown",
            "desktop": "unknown",
            "screen_width": 0,
            "screen_height": 0,
            "monitors": 0,
            "error": str(exc),
        }


def is_desktop_accessible() -> bool:
    """Check if the current Windows desktop session is interactive and accessible."""
    info = get_desktop_session_info()
    return bool(info.get("interactive", False))

