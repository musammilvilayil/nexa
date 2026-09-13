from __future__ import annotations

import re
import time
from typing import Any, Mapping

from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from browser.browsercontrol_adapter import BrowserControlAdapter

_NAV_RE = re.compile(r"^(?:navigate\s+(?:to\s+)?|go\s+to\s+|visit\s+)(https?://\S+|www\.\S+|[a-zA-Z0-9_\-]+\.[a-z]{2,}(?:/\S*)?)$", re.IGNORECASE)
_SCROLL_RE = re.compile(r"^(?:scroll\s+(?:down|up)(?:\s+(\d+))?|page\s+scroll)$", re.IGNORECASE)


class WebNavigationSkill:
    """High-level Web Navigation skill with landing verification and consent dialog handling."""

    def __init__(self, adapter: BrowserControlAdapter | None = None) -> None:
        self.adapter = adapter
        self.metadata = SkillMetadata(
            name="web_navigation",
            version="1.0.0",
            description="Verified page navigation, modal dismissal, and content scrolling",
            operations=(
                OperationSpec("navigate", "Navigate and verify page landing", RiskTier.REMOTE),
                OperationSpec("scroll_content", "Scroll page viewport to reveal content", RiskTier.MUTATE),
                OperationSpec("dismiss_dialogs", "Dismiss cookie consent or modal popups", RiskTier.MUTATE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = text.strip().rstrip(".!?")
        m = _NAV_RE.fullmatch(normalized)
        if m:
            return SkillMatch("web_navigation", "navigate", {"url": m.group(1).strip()})

        m_scroll = _SCROLL_RE.fullmatch(normalized)
        if m_scroll:
            direction = "up" if "up" in normalized.lower() else "down"
            amount = int(m_scroll.group(1)) if m_scroll.group(1) else 250
            return SkillMatch("web_navigation", "scroll_content", {"direction": direction, "amount": amount})

        if "dismiss popup" in normalized.lower() or "accept cookies" in normalized.lower():
            return SkillMatch("web_navigation", "dismiss_dialogs")

        return None

    def validate(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        if operation == "navigate":
            url = str(params.get("url", "")).strip()
            if not url:
                raise ValueError("URL cannot be empty")
            return {"url": url}
        return dict(params)

    def execute(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any]) -> ExecutionResult:
        if not self.adapter:
            return ExecutionResult(False, "BrowserControlAdapter not configured for WebNavigationSkill")

        try:
            if not self.adapter.is_connected:
                self.adapter.start()

            if operation == "navigate":
                url = params["url"]
                res = self.adapter.navigate(url)

                # Observe page
                obs = self.adapter.observe()

                # Verify landing via evaluation
                landing_info = self.adapter.evaluate("""
                (() => ({
                    title: document.title,
                    url: window.location.href,
                    readyState: document.readyState
                }))()
                """) or {}

                return ExecutionResult(
                    success=True,
                    message=f"Landed on {landing_info.get('title', 'page')} ({landing_info.get('url', url)})",
                    data={
                        "landing": landing_info,
                        "observation_id": obs.observation_id,
                    },
                )

            elif operation == "scroll_content":
                direction = params.get("direction", "down")
                amount = int(params.get("amount", 250))
                delta_y = amount if direction == "down" else -amount

                obs = self.adapter.observe()
                self.adapter.scroll(obs.observation_id, x=200, y=200, delta_x=0, delta_y=delta_y)
                new_obs = self.adapter.observe()

                return ExecutionResult(
                    success=True,
                    message=f"Scrolled {direction} by {amount}px",
                    data={"observation_id": new_obs.observation_id},
                )

            elif operation == "dismiss_dialogs":
                # Detect and dismiss cookie banners
                dismissed = self.adapter.evaluate("""
                (() => {
                    const buttons = Array.from(document.querySelectorAll('button, a'));
                    const consentBtn = buttons.find(b => {
                        const t = (b.innerText || '').toLowerCase();
                        return t.includes('accept all') || t.includes('agree') || t.includes('accept cookies') || t.includes('i agree');
                    });
                    if (consentBtn) {
                        consentBtn.click();
                        return true;
                    }
                    return false;
                })()
                """)
                return ExecutionResult(
                    success=True,
                    message="Dismissed modal/cookie dialog" if dismissed else "No modal dialog found",
                    data={"dismissed": bool(dismissed)},
                )

            return ExecutionResult(False, f"Unknown operation {operation}")
        except Exception as exc:
            return ExecutionResult(False, f"WebNavigation failed: {exc}", error=str(exc))
