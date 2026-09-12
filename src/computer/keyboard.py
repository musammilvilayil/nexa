from __future__ import annotations
import re
import time

from computer.contracts import FailsafeMonitor
from core.failsafe import FailsafeMonitor as CoreFailsafe


class KeyboardController:
    def __init__(self, failsafe: FailsafeMonitor | None = None):
        self._failsafe = failsafe or CoreFailsafe()
        self._pynput_keyboard = None
        self._controller = None
        self._secret_patterns = (
            re.compile(r"(?:api[_-]?key|secret|password|bearer|token)\s*[:=]\s*\S+", re.IGNORECASE),
            re.compile(r"\b(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,})\b"),
        )

    def _get_controller(self):
        if self._controller is None:
            try:
                try:
                    from computer.win32_desktop import ensure_desktop_attached
                    ensure_desktop_attached()
                except Exception:
                    pass
                from pynput import keyboard
                self._pynput_keyboard = keyboard
                self._controller = keyboard.Controller()
            except ImportError:
                raise RuntimeError("pynput library is required for keyboard control")
        return self._controller

    def _check_secrets(self, text: str) -> None:
        for pat in self._secret_patterns:
            if pat.search(text):
                raise ValueError(f"Blocked attempt to type potential secret/password: matches secret pattern.")
        text_upper = text.upper()
        for pattern in ["SECRET_KEY", "API_KEY", "PASSWORD", "AUTH_TOKEN", "BEARER", "SECRET"]:
            if pattern in text_upper:
                raise ValueError(f"Blocked attempt to type potential secret/password: matches '{pattern}'.")

    def type_text(self, text: str, interval: float = 0.05) -> None:
        self._failsafe.check_before_action()
        self._check_secrets(text)
        
        ctrl = self._get_controller()
        for char in text:
            ctrl.type(char)
            if interval > 0:
                time.sleep(interval)

    def press(self, key: str) -> None:
        self._failsafe.check_before_action()
        
        ctrl = self._get_controller()
        try:
            k = getattr(self._pynput_keyboard.Key, key)
        except AttributeError:
            k = key
            
        ctrl.press(k)
        ctrl.release(k)

    def hotkey(self, *keys: str) -> None:
        self._failsafe.check_before_action()
            
        ctrl = self._get_controller()
        parsed_keys = []
        for k in keys:
            subkeys = k.split("+") if "+" in k else [k]
            for sk in subkeys:
                sk_clean = sk.strip().lower()
                try:
                    parsed_keys.append(getattr(self._pynput_keyboard.Key, sk_clean))
                except AttributeError:
                    parsed_keys.append(sk_clean)

        for k in parsed_keys:
            ctrl.press(k)
        for k in reversed(parsed_keys):
            ctrl.release(k)

    def key_down(self, key: str) -> None:
        self._failsafe.check_before_action()
            
        ctrl = self._get_controller()
        try:
            k = getattr(self._pynput_keyboard.Key, key)
        except AttributeError:
            k = key
        ctrl.press(k)

    def key_up(self, key: str) -> None:
        self._failsafe.check_before_action()
            
        ctrl = self._get_controller()
        try:
            k = getattr(self._pynput_keyboard.Key, key)
        except AttributeError:
            k = key
        ctrl.release(k)
