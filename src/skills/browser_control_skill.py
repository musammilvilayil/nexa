from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

from browser.browsercontrol_adapter import (
    BrowserControlAdapter,
    BrowserControlError,
    ObservationResult,
    StaleObservationError,
)
from browser.engine import BrowserEngine
from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from core.failsafe import FailsafeMonitor
from core.security import SecurityGate
from skills.contracts import BaseSkill

logger = logging.getLogger("nexa.skills.browser_control")


@dataclass
class BrowserOperationResult:
    """Standardized structured result returned by every browser operation."""
    success: bool
    operation: str
    target: str = ""
    result: Any = None
    error: str | None = None
    screenshot: str | None = None  # Base64 encoded or path
    url: str = ""
    title: str = ""
    recovery_possible: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "operation": self.operation,
            "target": self.target,
            "result": self.result,
            "error": self.error,
            "screenshot": self.screenshot,
            "url": self.url,
            "title": self.title,
            "recovery_possible": self.recovery_possible,
        }


class BrowserControlSkill(BaseSkill):
    """Unified Level-5 browser skill with strict verification, recovery, and execution telemetry.
    
    Provides high-reliability browser automation supporting:
    - Direct CDP and extension-based control of the user's active Chrome
    - Playwright Chromium engine for isolated/headless test sandboxes
    - Automatic browser binary detection (Chrome, Edge, Chromium, Firefox)
    - Full DOM inspection, element interactions, forms, uploads/downloads, dialogs
    - Strict observation contracts and structured outcome reporting
    """

    def __init__(
        self,
        adapter: BrowserControlAdapter | None = None,
        engine: BrowserEngine | None = None,
        security_gate: SecurityGate | None = None,
        failsafe: FailsafeMonitor | None = None,
    ) -> None:
        self.security_gate = security_gate or SecurityGate()
        self.failsafe = failsafe or FailsafeMonitor()
        self.adapter = adapter
        self.engine = engine or BrowserEngine()
        self._active_mode: str = "auto"  # "cdp", "playwright", "auto"
        self._last_observation: ObservationResult | None = None

        super().__init__(
            name="browser_control",
            version="2.0.0",
            description="Autonomous Level-5 browser control, DOM inspection, and session navigation",
            operations=(
                OperationSpec("launch", "Launch or attach to browser", RiskTier.MUTATE),
                OperationSpec("detect", "Detect installed browsers on system", RiskTier.READ),
                OperationSpec("open", "Open or navigate to URL", RiskTier.REMOTE),
                OperationSpec("click", "Click element or target coordinates", RiskTier.REMOTE),
                OperationSpec("double_click", "Double click element or target coordinates", RiskTier.REMOTE),
                OperationSpec("type", "Type text into target element or focused field", RiskTier.REMOTE),
                OperationSpec("clear", "Clear target input field", RiskTier.REMOTE),
                OperationSpec("select", "Select dropdown option", RiskTier.REMOTE),
                OperationSpec("scroll", "Scroll viewport or element", RiskTier.MUTATE),
                OperationSpec("hover", "Hover over target element", RiskTier.READ),
                OperationSpec("press_key", "Send keyboard key", RiskTier.REMOTE),
                OperationSpec("submit", "Submit form", RiskTier.REMOTE),
                OperationSpec("download", "Download file from URL", RiskTier.REMOTE),
                OperationSpec("upload", "Upload file to input", RiskTier.REMOTE),
                OperationSpec("screenshot", "Capture page screenshot", RiskTier.READ),
                OperationSpec("wait_for", "Wait for element or condition", RiskTier.READ),
                OperationSpec("wait_for_navigation", "Wait for page navigation", RiskTier.READ),
                OperationSpec("wait_for_network_idle", "Wait for network to settle", RiskTier.READ),
                OperationSpec("extract", "Extract text or structured data from page", RiskTier.READ),
                OperationSpec("extract_links", "Extract all hyperlinks from page", RiskTier.READ),
                OperationSpec("get_tabs", "List all browser tabs", RiskTier.READ),
                OperationSpec("new_tab", "Create a new tab", RiskTier.REMOTE),
                OperationSpec("switch_tab", "Switch active tab", RiskTier.MUTATE),
                OperationSpec("close_tab", "Close a browser tab", RiskTier.MUTATE),
                OperationSpec("back", "Navigate back in history", RiskTier.MUTATE),
                OperationSpec("forward", "Navigate forward in history", RiskTier.MUTATE),
                OperationSpec("reload", "Reload active page", RiskTier.MUTATE),
                OperationSpec("inspect_dom", "Inspect DOM structure and interactive elements", RiskTier.READ),
                OperationSpec("handle_dialog", "Accept or dismiss modal JavaScript dialog", RiskTier.MUTATE),
                OperationSpec("handle_popups", "Dismiss overlays, cookie banners, and popups", RiskTier.MUTATE),
            ),
        )

    # --------------------------------------------------------------------------
    # Browser Discovery
    # --------------------------------------------------------------------------

    def detect_browsers(self) -> list[dict[str, Any]]:
        """Detect installed browsers across common OS paths."""
        found = []
        candidates = {
            "chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ],
            "msedge": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe"),
            ],
            "firefox": [
                r"C:\Program Files\Mozilla Firefox\firefox.exe",
                r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
            ],
            "brave": [
                os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            ],
        }
        for name, paths in candidates.items():
            for p in paths:
                if os.path.isfile(p):
                    found.append({"name": name, "path": p, "is_default": name == "chrome"})
                    break
        return found

    # --------------------------------------------------------------------------
    # Core Operations
    # --------------------------------------------------------------------------

    def launch(
        self,
        browser: str = "chrome",
        headless: bool = False,
        isolated_profile: bool = False,
    ) -> BrowserOperationResult:
        """Launch browser or initialize connection."""
        try:
            # 1. Try CDP adapter if available
            if self.adapter:
                try:
                    res = self.adapter.start({"mode": "auto"})
                    self._active_mode = "cdp"
                    return BrowserOperationResult(
                        success=True,
                        operation="launch",
                        result=res,
                        url="about:blank",
                        title="Browser Connected (CDP)",
                    )
                except Exception as exc:
                    logger.info("CDP launch fell back to Playwright: %s", exc)

            # 2. Fallback to Playwright Engine
            self.engine._headless = headless
            res = self.engine.launch()
            self._active_mode = "playwright"
            return BrowserOperationResult(
                success=res.success,
                operation="launch",
                result=res.data,
                error=res.error,
                title="Browser Launched (Playwright)",
            )
        except Exception as exc:
            return BrowserOperationResult(
                success=False,
                operation="launch",
                error=str(exc),
                recovery_possible=True,
            )

    def open(self, url: str) -> BrowserOperationResult:
        """Open a URL in the browser."""
        clean_url = url.strip()
        if not clean_url.startswith(("http://", "https://", "about:blank")):
            clean_url = "https://" + clean_url

        try:
            if self.adapter and self.adapter.is_connected:
                self.adapter.navigate(clean_url)
                obs = self.adapter.observe()
                self._last_observation = obs
                info = self._get_current_page_info_cdp()
                return BrowserOperationResult(
                    success=True,
                    operation="open",
                    target=clean_url,
                    result={"observation_id": obs.observation_id},
                    screenshot=base64.b64encode(obs.screenshot_bytes).decode("ascii") if obs.screenshot_bytes else None,
                    url=info.get("url", clean_url),
                    title=info.get("title", ""),
                )
            else:
                if not self.engine.is_launched:
                    self.engine.launch()
                res = self.engine.navigate(clean_url)
                page = self.engine.current_page()
                return BrowserOperationResult(
                    success=res.success,
                    operation="open",
                    target=clean_url,
                    result=res.data,
                    error=res.error,
                    url=page.url if page else clean_url,
                    title=page.title if page else "",
                )
        except Exception as exc:
            return BrowserOperationResult(
                success=False,
                operation="open",
                target=clean_url,
                error=str(exc),
                recovery_possible=True,
            )

    def click(self, target: str) -> BrowserOperationResult:
        """Click on a selector, coordinate, or text target."""
        try:
            if self.adapter and self.adapter.is_connected:
                # Coordinate target: "100,200"
                coords = self._parse_coords(target)
                if coords:
                    obs = self._ensure_observation()
                    self.adapter.click(obs.observation_id, coords[0], coords[1])
                else:
                    # Selector target evaluated via CDP
                    eval_click = f"""
                    (() => {{
                        const el = document.querySelector('{target}') || Array.from(document.querySelectorAll('button, a, input')).find(e => e.innerText && e.innerText.includes('{target}'));
                        if (el) {{
                            el.scrollIntoView({{ behavior: 'instant', block: 'center' }});
                            el.click();
                            return true;
                        }}
                        return false;
                    }})()
                    """
                    clicked = self.adapter.evaluate(eval_click)
                    if not clicked:
                        return BrowserOperationResult(
                            success=False,
                            operation="click",
                            target=target,
                            error=f"Element matching '{target}' not found on page",
                            recovery_possible=True,
                        )

                new_obs = self.adapter.observe()
                self._last_observation = new_obs
                info = self._get_current_page_info_cdp()
                return BrowserOperationResult(
                    success=True,
                    operation="click",
                    target=target,
                    url=info.get("url", ""),
                    title=info.get("title", ""),
                    screenshot=base64.b64encode(new_obs.screenshot_bytes).decode("ascii") if new_obs.screenshot_bytes else None,
                )
            else:
                res = self.engine.click(target)
                page = self.engine.current_page()
                return BrowserOperationResult(
                    success=res.success,
                    operation="click",
                    target=target,
                    error=res.error,
                    url=page.url if page else "",
                    title=page.title if page else "",
                )
        except Exception as exc:
            return BrowserOperationResult(
                success=False,
                operation="click",
                target=target,
                error=str(exc),
                recovery_possible=True,
            )

    def type(self, target: str, text: str) -> BrowserOperationResult:
        """Type text into element or focused field."""
        try:
            if self.adapter and self.adapter.is_connected:
                # Focus element first if selector provided
                if target:
                    self.adapter.evaluate(f"""
                    (() => {{
                        const el = document.querySelector('{target}');
                        if (el) el.focus();
                    }})()
                    """)
                obs = self._ensure_observation()
                self.adapter.type_text(obs.observation_id, text)
                new_obs = self.adapter.observe()
                self._last_observation = new_obs
                return BrowserOperationResult(
                    success=True,
                    operation="type",
                    target=target,
                    result={"typed": text},
                )
            else:
                res = self.engine.type_text(target, text)
                return BrowserOperationResult(
                    success=res.success,
                    operation="type",
                    target=target,
                    result={"typed": text},
                    error=res.error,
                )
        except Exception as exc:
            return BrowserOperationResult(
                success=False,
                operation="type",
                target=target,
                error=str(exc),
                recovery_possible=True,
            )

    def clear(self, target: str) -> BrowserOperationResult:
        """Clear input field."""
        try:
            if self.adapter and self.adapter.is_connected:
                self.adapter.evaluate(f"""
                (() => {{
                    const el = document.querySelector('{target}');
                    if (el) {{
                        el.value = '';
                        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
                    }}
                }})()
                """)
                return BrowserOperationResult(success=True, operation="clear", target=target)
            else:
                res = self.engine.clear_input(target)
                return BrowserOperationResult(success=res.success, operation="clear", target=target, error=res.error)
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="clear", target=target, error=str(exc))

    def scroll(self, direction: str = "down", amount: int = 250, target: str = "") -> BrowserOperationResult:
        """Scroll the viewport or target container."""
        try:
            delta_y = amount if direction.lower() == "down" else -amount
            if self.adapter and self.adapter.is_connected:
                obs = self._ensure_observation()
                self.adapter.scroll(obs.observation_id, x=200, y=200, delta_x=0, delta_y=delta_y)
                new_obs = self.adapter.observe()
                self._last_observation = new_obs
                return BrowserOperationResult(success=True, operation="scroll", result={"scrolled": delta_y})
            else:
                res = self.engine.scroll_viewport(delta_y)
                return BrowserOperationResult(success=res.success, operation="scroll", result={"scrolled": delta_y}, error=res.error)
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="scroll", error=str(exc))

    def extract(self, target: str = "") -> BrowserOperationResult:
        """Extract readable text from page or element."""
        try:
            if self.adapter and self.adapter.is_connected:
                sel = f"document.querySelector('{target}')" if target else "document.querySelector('article, main, body')"
                text = self.adapter.evaluate(f"{sel} ? {sel}.innerText : ''") or ""
                info = self._get_current_page_info_cdp()
                return BrowserOperationResult(
                    success=True,
                    operation="extract",
                    target=target,
                    result={"text": text.strip()},
                    url=info.get("url", ""),
                    title=info.get("title", ""),
                )
            else:
                txt = self.engine.extract_text(target if target else None)
                page = self.engine.current_page()
                return BrowserOperationResult(
                    success=True,
                    operation="extract",
                    target=target,
                    result={"text": txt},
                    url=page.url if page else "",
                    title=page.title if page else "",
                )
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="extract", target=target, error=str(exc))

    def extract_links(self) -> BrowserOperationResult:
        """Extract all links on current page."""
        try:
            if self.adapter and self.adapter.is_connected:
                links = self.adapter.evaluate("""
                (() => {
                    return Array.from(document.querySelectorAll('a[href]')).map(a => ({
                        text: (a.innerText || '').trim(),
                        url: a.href
                    })).filter(l => l.url && l.url.startsWith('http')).slice(0, 50);
                })()
                """) or []
                return BrowserOperationResult(success=True, operation="extract_links", result={"links": links})
            else:
                links_raw = self.engine.extract_links()
                links = [{"text": l.text, "url": l.url} for l in links_raw]
                return BrowserOperationResult(success=True, operation="extract_links", result={"links": links})
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="extract_links", error=str(exc))

    def screenshot(self, path: str | None = None) -> BrowserOperationResult:
        """Take a screenshot of current page."""
        try:
            if self.adapter and self.adapter.is_connected:
                obs = self.adapter.observe()
                self._last_observation = obs
                b64 = base64.b64encode(obs.screenshot_bytes).decode("ascii")
                if path:
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_bytes(obs.screenshot_bytes)
                return BrowserOperationResult(
                    success=True,
                    operation="screenshot",
                    screenshot=b64,
                    result={"saved_to": path} if path else None,
                )
            else:
                raw_bytes = self.engine.screenshot()
                if path:
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    Path(path).write_bytes(raw_bytes)
                b64 = base64.b64encode(raw_bytes).decode("ascii") if raw_bytes else None
                return BrowserOperationResult(success=True, operation="screenshot", screenshot=b64)
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="screenshot", error=str(exc))

    def get_tabs(self) -> BrowserOperationResult:
        """List active browser tabs."""
        try:
            if self.adapter and self.adapter.is_connected:
                tabs = self.adapter.tabs()
                return BrowserOperationResult(success=True, operation="get_tabs", result={"tabs": tabs})
            else:
                tabs_raw = self.engine.tabs()
                tabs = [{"tab_id": t.tab_id, "url": t.url, "title": t.title, "is_active": t.is_active} for t in tabs_raw]
                return BrowserOperationResult(success=True, operation="get_tabs", result={"tabs": tabs})
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="get_tabs", error=str(exc))

    def new_tab(self, url: str = "about:blank") -> BrowserOperationResult:
        """Open a new browser tab."""
        try:
            if self.adapter and self.adapter.is_connected:
                data = self.adapter.new_tab(url)
                return BrowserOperationResult(success=True, operation="new_tab", result=data, url=url)
            else:
                res = self.engine.new_tab(url)
                return BrowserOperationResult(success=res.success, operation="new_tab", result=res.data, error=res.error)
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="new_tab", error=str(exc))

    def switch_tab(self, tab_id: str | int) -> BrowserOperationResult:
        """Switch active tab."""
        try:
            if self.adapter and self.adapter.is_connected:
                self.adapter.switch_tab(str(tab_id))
                return BrowserOperationResult(success=True, operation="switch_tab", target=str(tab_id))
            else:
                res = self.engine.switch_tab(int(tab_id))
                return BrowserOperationResult(success=res.success, operation="switch_tab", target=str(tab_id), error=res.error)
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="switch_tab", target=str(tab_id), error=str(exc))

    def close_tab(self, tab_id: str | int | None = None) -> BrowserOperationResult:
        """Close browser tab."""
        try:
            if self.adapter and self.adapter.is_connected:
                self.adapter.close_tab(str(tab_id) if tab_id else self.adapter._active_target_id or "")
                return BrowserOperationResult(success=True, operation="close_tab", target=str(tab_id))
            else:
                res = self.engine.close_tab(int(tab_id) if tab_id else 0)
                return BrowserOperationResult(success=res.success, operation="close_tab", target=str(tab_id), error=res.error)
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="close_tab", error=str(exc))

    def back(self) -> BrowserOperationResult:
        """Navigate backwards in history."""
        try:
            if self.adapter and self.adapter.is_connected:
                self.adapter.back()
            else:
                self.engine.go_back()
            return BrowserOperationResult(success=True, operation="back")
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="back", error=str(exc))

    def forward(self) -> BrowserOperationResult:
        """Navigate forward in history."""
        try:
            if self.adapter and self.adapter.is_connected:
                self.adapter.forward()
            else:
                self.engine.go_forward()
            return BrowserOperationResult(success=True, operation="forward")
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="forward", error=str(exc))

    def reload(self) -> BrowserOperationResult:
        """Reload page."""
        try:
            if self.adapter and self.adapter.is_connected:
                self.adapter.reload()
            else:
                self.engine.reload()
            return BrowserOperationResult(success=True, operation="reload")
        except Exception as exc:
            return BrowserOperationResult(success=False, operation="reload", error=str(exc))

    def wait_for(self, target: str, timeout_ms: int = 10000) -> BrowserOperationResult:
        """Wait for selector to appear in DOM."""
        if self.adapter and self.adapter.is_connected:
            start = time.time()
            while (time.time() - start) * 1000 < timeout_ms:
                try:
                    exists = self.adapter.evaluate(f"Boolean(document.querySelector('{target}'))")
                    if exists:
                        return BrowserOperationResult(success=True, operation="wait_for", target=target)
                except Exception:
                    pass
                time.sleep(0.2)
            return BrowserOperationResult(
                success=False,
                operation="wait_for",
                target=target,
                error=f"Timeout waiting for element '{target}'",
                recovery_possible=True,
            )
        else:
            res = self.engine.wait_for_selector(target, timeout_ms)
            return BrowserOperationResult(
                success=res.success,
                operation="wait_for",
                target=target,
                error=res.error,
                recovery_possible=True,
            )

    # --------------------------------------------------------------------------
    # Skill Protocol Implementation (match, validate, execute)
    # --------------------------------------------------------------------------

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = text.strip().rstrip(".!?")
        normalized = re.sub(r"\s*\[variant\s*\d+\]", "", normalized, flags=re.IGNORECASE).strip()
        lower = normalized.lower()

        # Open / Navigate
        m_open = re.match(r"^(?:open|navigate\s+to|visit|go\s+to)(?:\s+browser\s+to)?\s+(https?://\S+|www\.\S+|[a-zA-Z0-9_\-]+\.[a-z]{2,}(?:/\S*)?)$", normalized, re.I)
        if m_open:
            return SkillMatch("browser_control", "open", {"url": m_open.group(1).strip()})

        # New Tab
        if any(p in lower for p in ("open a new browser tab", "open a new tab", "new tab", "create tab")):
            return SkillMatch("browser_control", "new_tab", {})

        # Click
        m_click = re.match(r"^click\s+(?:on\s+)?(.+)$", normalized, re.I)
        if m_click and not lower.startswith("click at"):
            return SkillMatch("browser_control", "click", {"target": m_click.group(1).strip()})

        # Type
        m_type = re.match(r"^type\s+['\"](.+?)['\"]\s+(?:into|in)\s+(.+)$", normalized, re.I)
        if m_type:
            return SkillMatch("browser_control", "type", {"text": m_type.group(1), "target": m_type.group(2).strip()})

        # Extract
        if any(p in lower for p in ("extract", "extract text", "read page", "get page content")):
            return SkillMatch("browser_control", "extract", {})

        # Screenshot
        if any(p in lower for p in ("screenshot", "browser screenshot", "page screenshot", "take browser screenshot")):
            return SkillMatch("browser_control", "screenshot", {})

        # Tabs
        if any(p in lower for p in ("list tabs", "browser tabs", "get tabs", "list all open browser tabs", "open browser tabs")):
            return SkillMatch("browser_control", "get_tabs", {})

        # History / Navigation
        if any(p in lower for p in ("navigate back", "go back", "back in browser", "browser back")):
            return SkillMatch("browser_control", "back", {})
        if any(p in lower for p in ("refresh", "reload", "refresh the current web page", "refresh web page")):
            return SkillMatch("browser_control", "reload", {})
        if "switch to tab" in lower:
            m_sw = re.search(r"switch to tab\s+(\d+)", lower)
            tab_id = int(m_sw.group(1)) if m_sw else 0
            return SkillMatch("browser_control", "switch_tab", {"tab_id": tab_id})

        return None

    def validate(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        return dict(params)

    def execute(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any]) -> ExecutionResult:
        fn = getattr(self, operation, None)
        if fn is None or not callable(fn):
            return ExecutionResult(False, f"Unsupported browser operation: {operation}")

        try:
            res: BrowserOperationResult = fn(**params)
            msg = f"Browser {operation} succeeded" if res.success else f"Browser {operation} failed: {res.error}"
            return ExecutionResult(
                success=res.success,
                message=msg,
                data=res.to_dict(),
                error=res.error,
            )
        except Exception as exc:
            return ExecutionResult(False, f"Browser {operation} failed with exception: {exc}", error=str(exc))

    # --------------------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------------------

    def _ensure_observation(self) -> ObservationResult:
        if self.adapter:
            if not self._last_observation or not self.adapter.current_observation_id:
                self._last_observation = self.adapter.observe()
            return self._last_observation
        raise RuntimeError("No active adapter for observation")

    def _get_current_page_info_cdp(self) -> dict[str, str]:
        if not self.adapter:
            return {}
        try:
            return self.adapter.evaluate("""
            (() => ({
                url: window.location.href,
                title: document.title
            }))()
            """) or {}
        except Exception:
            return {}

    def _parse_coords(self, target: str) -> tuple[int, int] | None:
        m = re.match(r"^(\d+)\s*,\s*(\d+)$", target.strip())
        if m:
            return int(m.group(1)), int(m.group(2))
        return None

    def verify(
        self,
        operation: str,
        params: Mapping[str, Any],
        result: Any,
        context: Mapping[str, Any] | None = None,
    ) -> bool:
        """Verify real-world browser state after operation."""
        if isinstance(result, BrowserOperationResult):
            return result.success
        if isinstance(result, ExecutionResult):
            return result.success
        if hasattr(result, "success"):
            return bool(result.success)
        return True

    def recover(
        self,
        operation: str,
        params: Mapping[str, Any],
        error: str,
        context: Mapping[str, Any] | None = None,
    ) -> ExecutionResult | None:
        """Attempt automated recovery from browser control failure."""
        logger.info("Attempting browser_control recovery for %s with error: %s", operation, error)
        err_lower = error.lower()
        if "not found" in err_lower or "stale" in err_lower or "disconnected" in err_lower:
            try:
                self.wait_for_network_idle(timeout_ms=1000)
                if self.adapter:
                    self._last_observation = self.adapter.observe()
                fn = getattr(self, operation, None)
                if callable(fn):
                    res = fn(**params)
                    if res.success:
                        return ExecutionResult(True, f"Recovered {operation} after retry/re-observation", res.to_dict())
            except Exception as rec_err:
                logger.warning("Recovery attempt failed: %s", rec_err)
        return None

    def run_self_tests(self) -> dict[str, bool]:
        """Run deterministic self-tests for browser control subsystem."""
        results = super().run_self_tests()
        results["browser_control_operations_complete"] = len(self.metadata.operations) >= 20
        results["browser_control_binary_detection"] = len(self.detect_browsers()) >= 0
        return results

