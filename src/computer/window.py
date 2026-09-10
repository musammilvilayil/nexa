from __future__ import annotations
import sys
import os
import re
from pathlib import Path

from computer.contracts import WindowInfo


class WindowManager:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("WindowManager is Windows-only for now.")

    def _ensure_desktop(self) -> None:
        try:
            from computer.win32_desktop import ensure_desktop_attached
            ensure_desktop_attached()
        except Exception:
            pass

    def _get_process_name(self, hwnd: int) -> str:
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if not pid.value:
                return ""

            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            hproc = kernel32.OpenProcess(0x1000, False, pid.value)
            if not hproc:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                    return Path(buf.value).name
                return ""
            finally:
                kernel32.CloseHandle(hproc)
        except Exception:
            return ""

    def list_windows(self) -> list[WindowInfo]:
        self._ensure_desktop()
        import ctypes
        from ctypes import wintypes
        
        user32 = ctypes.windll.user32
        
        windows: list[WindowInfo] = []
        foreground_hwnd = user32.GetForegroundWindow()
        
        def enum_windows_proc(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    
                    proc_name = self._get_process_name(hwnd)

                    windows.append(WindowInfo(
                        handle=hwnd,
                        title=title,
                        process_name=proc_name,
                        rect=(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                        is_visible=True,
                        is_focused=(hwnd == foreground_hwnd)
                    ))
            return True
        
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.EnumWindows(EnumWindowsProc(enum_windows_proc), 0)
        return windows

    def find_window(self, title_pattern: str) -> WindowInfo | None:
        pattern = re.compile(title_pattern, re.IGNORECASE)
        for w in self.list_windows():
            if pattern.search(w.title) or (w.process_name and pattern.search(w.process_name)):
                return w
        return None

    def focus_window(self, handle: int) -> None:
        self._ensure_desktop()
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, 9)  # SW_RESTORE
        user32.BringWindowToTop(handle)
        user32.SetForegroundWindow(handle)

    def minimize(self, handle: int) -> None:
        self._ensure_desktop()
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, 6)  # SW_MINIMIZE

    def maximize(self, handle: int) -> None:
        self._ensure_desktop()
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, 3)  # SW_MAXIMIZE

    def restore(self, handle: int) -> None:
        self._ensure_desktop()
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, 9)  # SW_RESTORE

    def close(self, handle: int) -> None:
        self._ensure_desktop()
        import ctypes
        user32 = ctypes.windll.user32
        user32.PostMessageW(handle, 0x0010, 0, 0)  # WM_CLOSE

    def get_active_window(self) -> WindowInfo | None:
        self._ensure_desktop()
        import ctypes
        from ctypes import wintypes
        
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
            
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length > 0:
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            title = buff.value
            
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        proc_name = self._get_process_name(hwnd)
        
        return WindowInfo(
            handle=hwnd,
            title=title,
            process_name=proc_name,
            rect=(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
            is_visible=True,
            is_focused=True
        )
