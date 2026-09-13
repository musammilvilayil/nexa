from __future__ import annotations
from typing import Any

from computer.contracts import Point, MouseButton, FailsafeMonitor
from core.failsafe import FailsafeMonitor as CoreFailsafe


class MouseController:
    def __init__(self, failsafe: FailsafeMonitor | None = None, audit_ledger: Any = None):
        self._failsafe = failsafe or CoreFailsafe()
        self._audit_ledger = audit_ledger
        self._pynput_mouse = None
        self._controller = None

    def _get_controller(self):
        if self._controller is None:
            try:
                try:
                    from computer.win32_desktop import ensure_desktop_attached
                    ensure_desktop_attached()
                except Exception:
                    pass
                from pynput import mouse
                self._pynput_mouse = mouse
                self._controller = mouse.Controller()
            except ImportError:
                raise RuntimeError("pynput library is required for mouse control")
        return self._controller

    def move_to(self, x: int, y: int) -> None:
        self._failsafe.check_before_action(mouse_x=x, mouse_y=y)
        ctrl = self._get_controller()
        ctrl.position = (x, y)

    def click(self, x: int, y: int, button: MouseButton = MouseButton.LEFT) -> None:
        self._failsafe.check_before_action(mouse_x=x, mouse_y=y)
        ctrl = self._get_controller()
        ctrl.position = (x, y)
        btn = getattr(self._pynput_mouse.Button, button.value)
        ctrl.click(btn)

    def double_click(self, x: int, y: int) -> None:
        self._failsafe.check_before_action(mouse_x=x, mouse_y=y)
        ctrl = self._get_controller()
        ctrl.position = (x, y)
        ctrl.click(self._pynput_mouse.Button.left, 2)

    def right_click(self, x: int, y: int) -> None:
        self._failsafe.check_before_action(mouse_x=x, mouse_y=y)
        ctrl = self._get_controller()
        ctrl.position = (x, y)
        ctrl.click(self._pynput_mouse.Button.right)

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int) -> None:
        self._failsafe.check_before_action(mouse_x=start_x, mouse_y=start_y)
        ctrl = self._get_controller()
        ctrl.position = (start_x, start_y)
        ctrl.press(self._pynput_mouse.Button.left)
        ctrl.position = (end_x, end_y)
        ctrl.release(self._pynput_mouse.Button.left)

    def scroll(self, x: int, y: int, clicks: int) -> None:
        self._failsafe.check_before_action(mouse_x=x, mouse_y=y)
        ctrl = self._get_controller()
        ctrl.position = (x, y)
        ctrl.scroll(0, clicks)

    def get_position(self) -> Point:
        self._failsafe.check_before_action()
        ctrl = self._get_controller()
        x, y = ctrl.position
        return Point(int(x), int(y))
