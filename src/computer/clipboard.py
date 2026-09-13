from __future__ import annotations
import sys


class ClipboardManager:
    def __init__(self):
        if sys.platform != "win32":
            raise RuntimeError("ClipboardManager is Windows-only for now.")
        self._secret_patterns = ["KEY", "SECRET", "PASSWORD", "TOKEN"]

    def _check_secrets(self, text: str) -> None:
        text_upper = text.upper()
        for pattern in self._secret_patterns:
            if pattern in text_upper:
                raise ValueError(f"Blocked attempt to write potential secret to clipboard: matches '{pattern}'.")

    def _setup_ctypes(self, user32, kernel32):
        import ctypes
        kernel32.GlobalAlloc.restype = ctypes.c_void_p
        kernel32.GlobalAlloc.argtypes = [ctypes.c_uint, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
        kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
        user32.SetClipboardData.restype = ctypes.c_void_p
        user32.SetClipboardData.argtypes = [ctypes.c_uint, ctypes.c_void_p]
        user32.GetClipboardData.restype = ctypes.c_void_p
        user32.GetClipboardData.argtypes = [ctypes.c_uint]

    def get_text(self) -> str:
        try:
            from computer.win32_desktop import ensure_desktop_attached
            ensure_desktop_attached()
        except Exception:
            pass

        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._setup_ctypes(user32, kernel32)
        
        import time
        opened = False
        for _ in range(10):
            if user32.OpenClipboard(0):
                opened = True
                break
            time.sleep(0.05)
        if not opened:
            return ""
        try:
            if user32.IsClipboardFormatAvailable(13):  # CF_UNICODETEXT
                handle = user32.GetClipboardData(13)
                if not handle:
                    return ""
                pcontents = kernel32.GlobalLock(handle)
                if not pcontents:
                    return ""
                try:
                    text = ctypes.c_wchar_p(pcontents).value
                    return text if text else ""
                finally:
                    kernel32.GlobalUnlock(handle)
            return ""
        finally:
            user32.CloseClipboard()

    def set_text(self, text: str) -> None:
        self._check_secrets(text)

        try:
            from computer.win32_desktop import ensure_desktop_attached
            ensure_desktop_attached()
        except Exception:
            pass
        
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self._setup_ctypes(user32, kernel32)
        
        import time
        opened = False
        for _ in range(10):
            if user32.OpenClipboard(0):
                opened = True
                break
            time.sleep(0.05)
        if not opened:
            raise RuntimeError("Failed to open Windows clipboard")
        try:
            user32.EmptyClipboard()
            count = len(text) + 1
            size = count * ctypes.sizeof(ctypes.c_wchar)
            handle = kernel32.GlobalAlloc(0x0042, size)
            if not handle:
                raise RuntimeError("GlobalAlloc failed for clipboard data")
            pcontents = kernel32.GlobalLock(handle)
            if not pcontents:
                raise RuntimeError("GlobalLock failed for clipboard data")
            try:
                buf = ctypes.create_unicode_buffer(text, count)
                ctypes.memmove(pcontents, buf, size)
            finally:
                kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(13, handle)  # CF_UNICODETEXT
        finally:
            user32.CloseClipboard()

    def clear(self) -> None:
        try:
            from computer.win32_desktop import ensure_desktop_attached
            ensure_desktop_attached()
        except Exception:
            pass

        import ctypes
        user32 = ctypes.windll.user32
        if user32.OpenClipboard(0):
            try:
                user32.EmptyClipboard()
            finally:
                user32.CloseClipboard()
