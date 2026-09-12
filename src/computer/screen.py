from __future__ import annotations

from computer.contracts import ScreenshotResult, FailsafeMonitor
from core.failsafe import FailsafeMonitor as CoreFailsafe


class ScreenCapture:
    def __init__(self, failsafe: FailsafeMonitor | None = None, monitor: int = 0):
        self._failsafe = failsafe or CoreFailsafe()
        self._default_monitor = monitor
        self._mss = None  # lazy import
    
    def _get_mss(self):
        if self._mss is None:
            try:
                try:
                    from computer.win32_desktop import ensure_desktop_attached
                    ensure_desktop_attached()
                except Exception:
                    pass
                import mss
                self._mss = mss.mss()
            except ImportError:
                raise RuntimeError("mss library is required for screen capture: pip install mss")
        return self._mss

    def capture(self, active_only: bool = False) -> bytes:
        """Convenience method returning raw screenshot bytes."""
        if active_only:
            return self.capture_active_window().image_bytes
        return self.capture_full().image_bytes

    def capture_full(self, monitor: int = 0) -> ScreenshotResult:
        self._failsafe.check_before_action()
        
        sct = self._get_mss()
        monitor_idx = monitor if monitor > 0 else self._default_monitor
        
        # Fallback to monitor 1 if the requested one is out of range
        if monitor_idx >= len(sct.monitors):
            monitor_idx = 1
            
        try:
            try:
                from computer.win32_desktop import ensure_desktop_attached
                ensure_desktop_attached()
            except Exception:
                pass
            sct_img = sct.grab(sct.monitors[monitor_idx])
            try:
                import mss.tools
                png_bytes = mss.tools.to_png(sct_img.rgb, sct_img.size)
            except Exception:
                png_bytes = sct_img.rgb
            return ScreenshotResult(
                image_bytes=png_bytes,
                width=sct_img.width,
                height=sct_img.height,
                monitor=monitor_idx
            )
        except Exception as exc:
            raise RuntimeError(f"Screen capture failed: {exc}") from exc

    def capture_region(self, x: int, y: int, width: int, height: int) -> ScreenshotResult:
        self._failsafe.check_before_action()
            
        sct = self._get_mss()
        monitor_dict = {"top": y, "left": x, "width": width, "height": height}
        try:
            sct_img = sct.grab(monitor_dict)
            try:
                import mss.tools
                png_bytes = mss.tools.to_png(sct_img.rgb, sct_img.size)
            except Exception:
                png_bytes = sct_img.rgb
            return ScreenshotResult(
                image_bytes=png_bytes,
                width=width,
                height=height
            )
        except Exception as exc:
            raise RuntimeError(f"Screen region capture failed: {exc}") from exc

    def capture_active_window(self, window_manager: Any | None = None) -> ScreenshotResult:
        """Capture screenshot of the currently active/foreground window."""
        self._failsafe.check_before_action()
        if window_manager is None:
            try:
                from computer.window import WindowManager
                window_manager = WindowManager()
            except Exception:
                return self.capture_full()
        try:
            active = window_manager.get_active_window()
            if not active or not active.rect:
                return self.capture_full()
            x, y, w, h = active.rect
            if w <= 10 or h <= 10:
                return self.capture_full()
            return self.capture_region(max(0, x), max(0, y), w, h)
        except Exception:
            return self.capture_full()

    def compare_screenshots(self, before: bytes, after: bytes) -> float:
        self._failsafe.check_before_action()
            
        # Simplified structural similarity for now
        if before == after:
            return 1.0
        return 0.0
