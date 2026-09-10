from __future__ import annotations

from computer.contracts import ScreenshotResult, FailsafeMonitor


class ScreenCapture:
    def __init__(self, failsafe: FailsafeMonitor | None = None, monitor: int = 0):
        self._failsafe = failsafe
        self._default_monitor = monitor
        self._mss = None  # lazy import
    
    def _get_mss(self):
        if self._mss is None:
            try:
                import mss
                self._mss = mss.mss()
            except ImportError:
                raise RuntimeError("mss library is required for screen capture: pip install mss")
        return self._mss

    def capture_full(self, monitor: int = 0) -> ScreenshotResult:
        if self._failsafe:
            self._failsafe.check_before_action()
        
        sct = self._get_mss()
        monitor_idx = monitor if monitor > 0 else self._default_monitor
        
        # Fallback to monitor 1 if the requested one is out of range
        if monitor_idx >= len(sct.monitors):
            monitor_idx = 1
            
        sct_img = sct.grab(sct.monitors[monitor_idx])
        return ScreenshotResult(
            image_bytes=sct_img.rgb,
            width=sct_img.width,
            height=sct_img.height,
            monitor=monitor_idx
        )

    def capture_region(self, x: int, y: int, width: int, height: int) -> ScreenshotResult:
        if self._failsafe:
            self._failsafe.check_before_action()
            
        sct = self._get_mss()
        monitor_dict = {"top": y, "left": x, "width": width, "height": height}
        sct_img = sct.grab(monitor_dict)
        return ScreenshotResult(
            image_bytes=sct_img.rgb,
            width=width,
            height=height
        )

    def compare_screenshots(self, before: bytes, after: bytes) -> float:
        if self._failsafe:
            self._failsafe.check_before_action()
            
        # Simplified structural similarity for now
        if before == after:
            return 1.0
        return 0.0
