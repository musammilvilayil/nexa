from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from providers.contracts import BoundingBox, UIElement


class VisionBackend(Protocol):
    """Minimal vision backend that ScreenAnalyzer depends on."""
    def analyze_image(self, image_bytes: bytes, prompt: str) -> dict[str, Any]: ...
    def is_available(self) -> bool: ...


@dataclass(frozen=True)
class ScreenState:
    """Represents the rich, structured current state of the screen."""
    active_window: str = ""
    active_application: str = ""
    visible_text: str = ""
    buttons: tuple[UIElement, ...] = ()
    inputs: tuple[UIElement, ...] = ()
    links: tuple[UIElement, ...] = ()
    menus: tuple[UIElement, ...] = ()
    dialogs: tuple[UIElement, ...] = ()
    elements: tuple[Any, ...] = ()
    description: str = ""
    confidence: float = 1.0
    timestamp: str = ""
    raw: Any = None


def inspect_window_semantic_elements(hwnd: int) -> tuple[UIElement, ...]:
    """Inspect semantic controls in a native Windows window using Win32 API.
    
    Prefers native control classification (buttons, edit controls, combo boxes,
    menus, lists) over blind pixel coordinates.
    """
    if sys.platform != "win32" or not hwnd:
        return ()

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        elements: list[UIElement] = []

        def enum_child_proc(chwnd: int, lparam: int) -> bool:
            if not user32.IsWindowVisible(chwnd):
                return True

            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(chwnd, cls_buf, 256)
            class_name = cls_buf.value.lower()

            length = user32.GetWindowTextLengthW(chwnd)
            text = ""
            if length > 0:
                text_buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(chwnd, text_buf, length + 1)
                text = text_buf.value

            rect = wintypes.RECT()
            user32.GetWindowRect(chwnd, ctypes.byref(rect))
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            bounds = BoundingBox(x=rect.left, y=rect.top, width=width, height=height)

            is_focused = (chwnd == user32.GetFocus())
            is_enabled = bool(user32.IsWindowEnabled(chwnd))

            # Determine element type from class
            elem_type = "unknown"
            if "button" in class_name:
                elem_type = "button"
            elif "edit" in class_name or "rich" in class_name:
                elem_type = "input"
            elif "combobox" in class_name or "listbox" in class_name:
                elem_type = "menu"
            elif "link" in class_name or "syslink" in class_name:
                elem_type = "link"
            elif "dialog" in class_name or "#32770" in class_name:
                elem_type = "dialog"
            elif "static" in class_name:
                elem_type = "label"

            name = text if text else f"{class_name}_{chwnd}"

            elements.append(
                UIElement(
                    name=name,
                    element_type=elem_type,
                    bounds=bounds,
                    text=text,
                    enabled=is_enabled,
                    focused=is_focused,
                )
            )
            return True

        user32.EnumChildWindows(hwnd, WNDENUMPROC(enum_child_proc), 0)
        return tuple(elements)
    except Exception:
        return ()


class ScreenAnalyzer:
    """Analyzes screenshots and native window trees to produce structured screen observation."""

    def __init__(
        self,
        backend: VisionBackend | None = None,
        window_manager: Any | None = None,
    ) -> None:
        self._backend = backend
        self._window_manager = window_manager

    @property
    def is_available(self) -> bool:
        return self._backend is not None and self._backend.is_available()

    def analyze(
        self,
        screenshot: bytes | None = None,
        *,
        prompt: str = "Describe what you see on the screen.",
    ) -> ScreenState:
        """Analyze current screen using semantic UI inspection + vision backend."""
        now = datetime.now(timezone.utc).isoformat()

        active_window_title = ""
        active_app = ""
        active_hwnd = 0

        if self._window_manager is not None:
            try:
                active_win = self._window_manager.get_active_window()
                if active_win:
                    active_window_title = active_win.title
                    active_app = active_win.process_name
                    active_hwnd = active_win.handle
            except Exception:
                pass

        # 1. Semantic Win32 accessibility inspection (preferred over raw pixel guessing)
        semantic_elements = inspect_window_semantic_elements(active_hwnd) if active_hwnd else ()
        buttons = tuple(e for e in semantic_elements if e.element_type == "button")
        inputs = tuple(e for e in semantic_elements if e.element_type == "input")
        links = tuple(e for e in semantic_elements if e.element_type == "link")
        menus = tuple(e for e in semantic_elements if e.element_type == "menu")
        dialogs = tuple(e for e in semantic_elements if e.element_type == "dialog")

        # 2. Vision provider analysis if backend is configured and screenshot provided
        if self._backend is not None and self._backend.is_available() and screenshot:
            try:
                result = self._backend.analyze_image(screenshot, prompt)
                vision_elements = tuple(result.get("elements", []))
                all_elements = tuple(list(semantic_elements) + list(vision_elements))
                return ScreenState(
                    active_window=result.get("active_window") or active_window_title,
                    active_application=active_app,
                    visible_text=result.get("visible_text", ""),
                    buttons=buttons,
                    inputs=inputs,
                    links=links,
                    menus=menus,
                    dialogs=dialogs,
                    elements=all_elements,
                    description=result.get("description", "Vision backend visual analysis"),
                    confidence=float(result.get("confidence", 0.95)),
                    timestamp=now,
                    raw=result,
                )
            except Exception as exc:
                return ScreenState(
                    active_window=active_window_title,
                    active_application=active_app,
                    buttons=buttons,
                    inputs=inputs,
                    links=links,
                    menus=menus,
                    dialogs=dialogs,
                    elements=semantic_elements,
                    description=f"Vision analysis failed: {exc}",
                    confidence=0.5,
                    timestamp=now,
                )

        # 3. If vision provider is unavailable, report truthful capability limitation
        desc = (
            f"Active: {active_app or 'Desktop'} | Window: {active_window_title or 'None'} "
            f"(Native UI semantic observation active, vision LLM provider unconfigured)"
            if active_window_title
            else "No vision backend configured and no active window detected"
        )

        return ScreenState(
            active_window=active_window_title,
            active_application=active_app,
            visible_text="",
            buttons=buttons,
            inputs=inputs,
            links=links,
            menus=menus,
            dialogs=dialogs,
            elements=semantic_elements,
            description=desc,
            confidence=1.0 if semantic_elements else 0.5,
            timestamp=now,
        )

    def verify_action(self, before: bytes, after: bytes, expected: str) -> bool:
        """Verify whether an action succeeded by comparing state."""
        if self._backend is None or not self._backend.is_available():
            # If screenshots differ, state changed
            return before != after

        try:
            result = self._backend.analyze_image(
                after,
                f"Compare with the previous state and determine if this action succeeded: {expected}. "
                f"Respond with a JSON object containing 'success': true or false.",
            )
            return bool(result.get("success", True))
        except Exception:
            return before != after

    def find_element(self, screenshot: bytes, description: str) -> dict[str, Any] | None:
        """Find a UI element by description using semantic tree or vision backend."""
        # Check active window semantic elements first
        if self._window_manager:
            active_win = self._window_manager.get_active_window()
            if active_win:
                semantic = inspect_window_semantic_elements(active_win.handle)
                desc_lower = description.lower()
                for el in semantic:
                    if desc_lower in el.name.lower() or (el.text and desc_lower in el.text.lower()):
                        return {
                            "found": True,
                            "name": el.name,
                            "text": el.text,
                            "type": el.element_type,
                            "x": el.bounds.x if el.bounds else 0,
                            "y": el.bounds.y if el.bounds else 0,
                            "width": el.bounds.width if el.bounds else 0,
                            "height": el.bounds.height if el.bounds else 0,
                        }

        if self._backend is None or not self._backend.is_available():
            return None

        try:
            result = self._backend.analyze_image(
                screenshot,
                f"Find the UI element matching this description: '{description}'. "
                f"Return a JSON with 'found': true/false, 'x': int, 'y': int, 'text': str",
            )
            if result.get("found"):
                return result
            return None
        except Exception:
            return None
