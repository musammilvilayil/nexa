from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AutomationTarget(str, Enum):
    BROWSER_DOM = "browser_dom"     # Web page elements, HTML forms, navigation, DOM text
    DESKTOP_UI = "desktop_ui"       # Window chrome, file dialogs, system tray, OS apps, notifications
    HYBRID = "hybrid"               # Multi-domain workflow (e.g. download web file then open in desktop app)


class AutomationCoordinator:
    """Coordinates and routes actions between Browser DOM and Windows Desktop layers.
    
    Decision Policy:
    1. If task is inside browser DOM -> use Playwright/DOM (fast, reliable selectors).
    2. If task requires OS-level interaction -> use DESKTOP_UI.
    3. If browser UI is obstructed or selector fails -> fallback to DESKTOP_UI.
    4. If desktop semantic controls are available -> prefer semantic automation.
    5. If semantic automation fails -> use visual/coordinate reasoning.
    Every transition is observable, logged, and audited.
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

    def __init__(self) -> None:
        self._transition_history: list[dict[str, Any]] = []

    @property
    def transition_history(self) -> list[dict[str, Any]]:
        return list(self._transition_history)

    def record_transition(
        self,
        source: AutomationTarget | str,
        target: AutomationTarget | str,
        reason: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Log and record an observable transition between automation domains."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "from": str(source),
            "to": str(target),
            "reason": reason,
            "details": details or {},
        }
        self._transition_history.append(record)
        logger.info(f"Automation transition: {source} -> {target} ({reason})")

    @classmethod
    def determine_target(cls, action_description: str, context: dict[str, Any] | None = None) -> AutomationTarget:
        """Analyze intent and context to select the most reliable automation mechanism."""
        desc_lower = action_description.lower()

        has_desktop = any(ind in desc_lower for ind in cls.NATIVE_DESKTOP_INDICATORS)
        has_browser = any(ind in desc_lower for ind in cls.BROWSER_DOM_INDICATORS)

        if has_desktop and has_browser:
            return AutomationTarget.HYBRID
        if has_desktop:
            return AutomationTarget.DESKTOP_UI
        if has_browser:
            return AutomationTarget.BROWSER_DOM

        if context:
            if context.get("active_layer") == "browser":
                return AutomationTarget.BROWSER_DOM
            if context.get("active_layer") == "desktop":
                return AutomationTarget.DESKTOP_UI

        if "http" in desc_lower or "www." in desc_lower or "search" in desc_lower:
            return AutomationTarget.BROWSER_DOM
        return AutomationTarget.DESKTOP_UI

    def fallback_on_obstruction(
        self,
        current_target: AutomationTarget,
        error_message: str,
    ) -> AutomationTarget:
        """Fallback to alternative execution layer if primary layer encounters an obstruction."""
        if current_target == AutomationTarget.BROWSER_DOM:
            target = AutomationTarget.DESKTOP_UI
            self.record_transition(
                current_target,
                target,
                f"Browser DOM obstructed or selector failed: {error_message}",
            )
            return target
        target = AutomationTarget.BROWSER_DOM
        self.record_transition(
            current_target,
            target,
            f"Desktop UI fallback requested: {error_message}",
        )
        return target

    def decompose_hybrid_intent(self, intent_text: str) -> list[dict[str, Any]]:
        """Decompose a high-level intent into sequential, domain-specific steps.
        
        Example: 'Open Chrome and search Google for MERN jobs' ->
        1. APP_CONTROL: launch Chrome
        2. BROWSER: navigate Google
        3. BROWSER_DOM: search
        4. BROWSER_DOM: extract results
        5. VERIFY: results exist
        """
        lower = intent_text.lower()
        steps = []
        if ("open chrome" in lower or "launch chrome" in lower) and "search" in lower:
            query = intent_text
            for prefix in ("open chrome and search google for", "search google for", "search for"):
                if prefix in lower:
                    idx = lower.index(prefix) + len(prefix)
                    query = intent_text[idx:].strip().rstrip(".!?")
                    break
            steps.append({"layer": "app_control", "action": "launch", "target": "Chrome"})
            steps.append({"layer": "browser_dom", "action": "search", "query": query})
            steps.append({"layer": "browser_dom", "action": "extract", "target": "results"})
            steps.append({"layer": "verify", "action": "verify_state", "expected": f"results_for_{query}"})
            return steps

        # Generic single-step fallback
        target = self.determine_target(intent_text)
        steps.append({"layer": target.value, "action": "execute", "intent": intent_text})
        return steps
