from __future__ import annotations
import time

from computer.contracts import FailsafeMonitor


class KeyboardController:
    def __init__(self, failsafe: FailsafeMonitor | None = None):
        self._failsafe = failsafe
        self._pynput_keyboard = None
        self._controller = None
        self._secret_patterns = ["KEY", "SECRET", "PASSWORD", "TOKEN"]

    def _get_controller(self):
        if self._controller is None:
            try:
                from pynput import keyboard
                self._pynput_keyboard = keyboard
                self._controller = keyboard.Controller()
            except ImportError:
                raise RuntimeError("pynput library is required for keyboard control")
        return self._controller

    def _check_secrets(self, text: str) -> None:
        text_upper = text.upper()
        for pattern in self._secret_patterns:
            if pattern in text_upper:
                raise ValueError(f"Blocked attempt to type potential secret/password: matches '{pattern}'.")

    def type_text(self, text: str, interval: float = 0.05) -> None:
        if self._failsafe:
            self._failsafe.check_before_action()
        self._check_secrets(text)
        
        ctrl = self._get_controller()
        for char in text:
            ctrl.type(char)
            if interval > 0:
                time.sleep(interval)

    def press(self, key: str) -> None:
        if self._failsafe:
            self._failsafe.check_before_action()
        
        ctrl = self._get_controller()
        try:
            k = getattr(self._pynput_keyboard.Key, key)
        except AttributeError:
            k = key
            
        ctrl.press(k)
        ctrl.release(k)

    def hotkey(self, *keys: str) -> None:
        if self._failsafe:
            self._failsafe.check_before_action()
            
        ctrl = self._get_controller()
        parsed_keys = []
        for k in keys:
            try:
                parsed_keys.append(getattr(self._pynput_keyboard.Key, k))
            except AttributeError:
                parsed_keys.append(k)

        for k in parsed_keys:
            ctrl.press(k)
        for k in reversed(parsed_keys):
            ctrl.release(k)

    def key_down(self, key: str) -> None:
        if self._failsafe:
            self._failsafe.check_before_action()
            
        ctrl = self._get_controller()
        try:
            k = getattr(self._pynput_keyboard.Key, key)
        except AttributeError:
            k = key
        ctrl.press(k)

    def key_up(self, key: str) -> None:
        if self._failsafe:
            self._failsafe.check_before_action()
            
        ctrl = self._get_controller()
        try:
            k = getattr(self._pynput_keyboard.Key, key)
        except AttributeError:
            k = key
        ctrl.release(k)
