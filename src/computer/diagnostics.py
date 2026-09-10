from __future__ import annotations

import sys
from typing import Any

from computer.win32_desktop import get_desktop_session_info, ensure_desktop_attached
from computer.screen import ScreenCapture
from computer.mouse import MouseController
from computer.keyboard import KeyboardController
from computer.clipboard import ClipboardManager
from computer.window import WindowManager
from core.failsafe import FailsafeMonitor


def run_desktop_check(failsafe: FailsafeMonitor | None = None) -> dict[str, Any]:
    """Perform a comprehensive health check on real interactive desktop availability."""
    info = get_desktop_session_info()
    
    # 1. Screen capture check
    screen_cap_avail = False
    screen_error = None
    try:
        sc = ScreenCapture(failsafe=failsafe)
        res = sc.capture_full()
        if res and len(res.image_bytes) > 0 and res.width > 0:
            screen_cap_avail = True
    except Exception as exc:
        screen_error = str(exc)

    # 2. Mouse control check
    mouse_avail = False
    mouse_error = None
    try:
        mc = MouseController(failsafe=failsafe)
        pos = mc.get_position()
        if pos is not None:
            mouse_avail = True
    except Exception as exc:
        mouse_error = str(exc)

    # 3. Keyboard control check
    keyboard_avail = False
    keyboard_error = None
    try:
        kc = KeyboardController(failsafe=failsafe)
        ctrl = kc._get_controller()
        if ctrl is not None:
            keyboard_avail = True
    except Exception as exc:
        keyboard_error = str(exc)

    # 4. Clipboard check
    clipboard_avail = False
    clipboard_error = None
    try:
        cb = ClipboardManager()
        # Non-destructive read check
        _ = cb.get_text()
        clipboard_avail = True
    except Exception as exc:
        clipboard_error = str(exc)

    # 5. Window manager check
    window_mgr_avail = False
    window_count = 0
    window_error = None
    try:
        wm = WindowManager()
        wins = wm.list_windows()
        window_mgr_avail = True
        window_count = len(wins)
    except Exception as exc:
        window_error = str(exc)

    # 6. Failsafe check
    fs_avail = failsafe is not None and not failsafe.is_stopped

    return {
        "interactive_session_detected": info.get("interactive", False),
        "station": info.get("station", "unknown"),
        "desktop": info.get("desktop", "unknown"),
        "screen_capture_available": screen_cap_avail,
        "screen_capture_error": screen_error,
        "monitor_count": info.get("monitors", 1),
        "screen_dimensions": f"{info.get('screen_width', 0)}x{info.get('screen_height', 0)}",
        "mouse_control_available": mouse_avail,
        "mouse_error": mouse_error,
        "keyboard_control_available": keyboard_avail,
        "keyboard_error": keyboard_error,
        "clipboard_available": clipboard_avail,
        "clipboard_error": clipboard_error,
        "window_manager_available": window_mgr_avail,
        "window_count": window_count,
        "window_error": window_error,
        "failsafe_available": fs_avail,
    }


def format_desktop_check(report: dict[str, Any]) -> str:
    """Format the desktop check dictionary into a clean CLI string."""
    lines = [
        "NEXA Interactive Desktop Diagnostics (/desktop-check):",
        f"  Interactive session: {'YES' if report['interactive_session_detected'] else 'NO'} ({report['station']}/{report['desktop']})",
        f"  Screen capture: {'AVAILABLE' if report['screen_capture_available'] else 'FAILED'}" + (f" ({report['screen_capture_error']})" if report.get('screen_capture_error') else ""),
        f"  Monitors: {report['monitor_count']}",
        f"  Screen dimensions: {report['screen_dimensions']}",
        f"  Mouse control: {'AVAILABLE' if report['mouse_control_available'] else 'UNAVAILABLE'}" + (f" ({report['mouse_error']})" if report.get('mouse_error') else ""),
        f"  Keyboard control: {'AVAILABLE' if report['keyboard_control_available'] else 'UNAVAILABLE'}" + (f" ({report['keyboard_error']})" if report.get('keyboard_error') else ""),
        f"  Clipboard: {'AVAILABLE' if report['clipboard_available'] else 'UNAVAILABLE'}" + (f" ({report['clipboard_error']})" if report.get('clipboard_error') else ""),
        f"  Window manager: {'AVAILABLE' if report['window_manager_available'] else 'UNAVAILABLE'} ({report['window_count']} windows enumerated)",
        f"  Failsafe monitor: {'ACTIVE & ARMED' if report['failsafe_available'] else 'STOPPED OR MISSING'}",
    ]
    return "\n".join(lines)
