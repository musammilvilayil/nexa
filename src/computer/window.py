from __future__ import annotations
import sys
import re

from computer.contracts import WindowInfo


class WindowManager:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("WindowManager is Windows-only for now.")

    def list_windows(self) -> list[WindowInfo]:
        import ctypes
        from ctypes import wintypes
        
        user32 = ctypes.windll.user32
        
        windows = []
        
        def enum_windows_proc(hwnd, lParam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value
                    
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    
                    windows.append(WindowInfo(
                        handle=hwnd,
                        title=title,
                        process_name="",
                        rect=(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
                        is_visible=True,
                        is_focused=(hwnd == user32.GetForegroundWindow())
                    ))
            return True
        
        EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        user32.EnumWindows(EnumWindowsProc(enum_windows_proc), 0)
        return windows

    def find_window(self, title_pattern: str) -> WindowInfo | None:
        pattern = re.compile(title_pattern)
        for w in self.list_windows():
            if pattern.search(w.title):
                return w
        return None

    def focus_window(self, handle: int) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        user32.SetForegroundWindow(handle)

    def minimize(self, handle: int) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, 6)  # SW_MINIMIZE

    def maximize(self, handle: int) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, 3)  # SW_MAXIMIZE

    def restore(self, handle: int) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        user32.ShowWindow(handle, 9)  # SW_RESTORE

    def close(self, handle: int) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        user32.PostMessageW(handle, 0x0010, 0, 0)  # WM_CLOSE

    def get_active_window(self) -> WindowInfo | None:
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
        
        return WindowInfo(
            handle=hwnd,
            title=title,
            rect=(rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top),
            is_visible=True,
            is_focused=True
        )
