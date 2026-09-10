from __future__ import annotations

from enum import Enum
from typing import Any


class AutomationTarget(str, Enum):
    BROWSER_DOM = "browser_dom"     # Web page elements, HTML forms, navigation, DOM text
    DESKTOP_UI = "desktop_ui"       # Window chrome, file dialogs, system tray, OS apps, notifications
    HYBRID = "hybrid"               # Multi-domain workflow (e.g. download web file then open in desktop app)


class AutomationCoordinator:
    """Coordinates and routes actions between Browser DOM and Windows Desktop layers.
    
    Invariants:
    1. DOM operations are preferred for web page interactions (reliable selectors, fast, headful/headless).
    2. Desktop automation is used for browser chrome (tabs, window controls), OS dialogs (file pickers, save dialogs),
       system notifications, and desktop applications.
    """

    NATIVE_DESKTOP_INDICATORS = (
        "file picker",
        "open file dialog",
        "save file dialog",
        "save as",
        "upload dialog",
        "print dialog",
        "browser window",
        "window focus",
        "window minimize",
        "os notification",
        "system tray",
        "desktop",
        "notepad",
        "explorer",
        "taskbar",
    )

    BROWSER_DOM_INDICATORS = (
        "http://",
        "https://",
        "google.com",
        "search google",
        "web page",
        "dom element",
        "css selector",
        "html",
        "click link",
        "submit form",
        "extract table",
        "read page",
    )

    @classmethod
    def determine_target(cls, action_description: str, context: dict[str, Any] | None = None) -> AutomationTarget:
        """Analyze intent and context to select the most reliable automation mechanism."""
        desc_lower = action_description.lower()

        # Check native desktop indicators first
        has_desktop = any(ind in desc_lower for ind in cls.NATIVE_DESKTOP_INDICATORS)
        has_browser = any(ind in desc_lower for ind in cls.BROWSER_DOM_INDICATORS)

        if has_desktop and has_browser:
            return AutomationTarget.HYBRID
        if has_desktop:
            return AutomationTarget.DESKTOP_UI
        if has_browser:
            return AutomationTarget.BROWSER_DOM

        # Context-based routing
        if context:
            if context.get("active_layer") == "browser":
                return AutomationTarget.BROWSER_DOM
            if context.get("active_layer") == "desktop":
                return AutomationTarget.DESKTOP_UI

        # Default heuristic: if mentions URLs or web terms, browser DOM, otherwise desktop
        if "http" in desc_lower or "www." in desc_lower or "search" in desc_lower:
            return AutomationTarget.BROWSER_DOM
        return AutomationTarget.DESKTOP_UI
