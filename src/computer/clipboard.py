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

    def get_text(self) -> str:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        
        user32.OpenClipboard(0)
        try:
            if user32.IsClipboardFormatAvailable(13):  # CF_UNICODETEXT
                handle = user32.GetClipboardData(13)
                if not handle:
                    return ""
                pcontents = kernel32.GlobalLock(handle)
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
        
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        
        user32.OpenClipboard(0)
        try:
            user32.EmptyClipboard()
            count = len(text) + 1
            size = count * ctypes.sizeof(ctypes.c_wchar)
            handle = kernel32.GlobalAlloc(0x0042, size)
            pcontents = kernel32.GlobalLock(handle)
            try:
                buf = ctypes.create_unicode_buffer(text, count)
                ctypes.memmove(pcontents, buf, size)
            finally:
                kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(13, handle)  # CF_UNICODETEXT
        finally:
            user32.CloseClipboard()

    def clear(self) -> None:
        import ctypes
        user32 = ctypes.windll.user32
        user32.OpenClipboard(0)
        try:
            user32.EmptyClipboard()
        finally:
            user32.CloseClipboard()
