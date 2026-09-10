from __future__ import annotations

import re
from typing import Any, Mapping

from browser.engine import BrowserEngine
from browser.navigator import WebNavigator
from core import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata

# open: `open (.+)`, `browse (.+)`, `go to (.+)`, `/browser open (.+)`, `browser open cheythu (.+) open cheyy`
_OPEN_RE = re.compile(
    r"^(?:open\s+(.+)|browse\s+(.+)|go\s+to\s+(.+)|/browser\s+open\s+(.+)|browser\s+open\s+cheythu\s+(.+)\s+open\s+cheyy)$",
    re.IGNORECASE
)

# search: `search (?:google |web )?(?:for )?(.+)`, `google search (.+)`, `/search (.+)`, `google il (.+) search cheyy`
_SEARCH_RE = re.compile(
    r"^(?:search\s+(?:google\s+|web\s+)?(?:for\s+)?(.+)|google\s+search\s+(.+)|/search\s+(.+)|google\s+il\s+(.+)\s+search\s+cheyy)$",
    re.IGNORECASE
)

# click_element: `click (?:on )?(.+)`, `browser click (.+)`
_CLICK_RE = re.compile(r"^(?:click\s+(?:on\s+)?(.+)|browser\s+click\s+(.+))$", re.IGNORECASE)

# type_in_field: `type "(.+)" (?:in|into) (.+)`
_TYPE_RE = re.compile(r"^type\s+\"(.+)\"\s+(?:in|into)\s+(.+)$", re.IGNORECASE)

# extract: `extract (?:text|data|content)`, `read page`, `page text`
_EXTRACT_RE = re.compile(r"^(?:extract\s+(?:text|data|content)|read\s+page|page\s+text)$", re.IGNORECASE)

# screenshot: `page screenshot`, `browser screenshot`
_SCREENSHOT_RE = re.compile(r"^(?:page\s+screenshot|browser\s+screenshot)$", re.IGNORECASE)

# tab_list: `list tabs`, `browser tabs`, `/tabs`
_TAB_LIST_RE = re.compile(r"^(?:list\s+tabs|browser\s+tabs|/tabs)$", re.IGNORECASE)

# tab_close: `close tab (\d+)`, `close (?:this|current) tab`
_TAB_CLOSE_RE = re.compile(r"^(?:close\s+tab\s+(\d+)|close\s+(?:this|current)\s+tab)$", re.IGNORECASE)

# launch: `launch browser`, `open browser`, `start browser`, `browser launch cheyy`, `chrome open cheyy`
_LAUNCH_RE = re.compile(
    r"^(?:launch\s+browser|open\s+browser|start\s+browser|browser\s+launch\s+cheyy|chrome\s+open\s+cheyy)$",
    re.IGNORECASE
)

# close_browser: `close browser`, `browser close cheyy`
_CLOSE_RE = re.compile(r"^(?:close\s+browser|browser\s+close\s+cheyy)$", re.IGNORECASE)


class BrowserSkill:
    """Browser automation skill."""

    def __init__(self, engine: BrowserEngine | None = None, navigator: WebNavigator | None = None) -> None:
        self.engine = engine or BrowserEngine()
        self.navigator = navigator or WebNavigator(self.engine)
        
        self.metadata = SkillMetadata(
            name="browser",
            version="0.1.0",
            description="Browser automation and web navigation",
            operations=(
                OperationSpec("open", "Open URL in browser", RiskTier.REMOTE),
                OperationSpec("search", "Search the web", RiskTier.REMOTE),
                OperationSpec("click_element", "Click element on page", RiskTier.REMOTE),
                OperationSpec("type_in_field", "Type text in page field", RiskTier.REMOTE),
                OperationSpec("extract", "Extract page text", RiskTier.READ),
                OperationSpec("screenshot", "Take page screenshot", RiskTier.READ),
                OperationSpec("tab_list", "List browser tabs", RiskTier.READ),
                OperationSpec("tab_close", "Close a browser tab", RiskTier.MUTATE),
                OperationSpec("download", "Download a file", RiskTier.REMOTE),
                OperationSpec("launch", "Launch browser", RiskTier.MUTATE),
                OperationSpec("close_browser", "Close browser", RiskTier.MUTATE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = text.strip()
        
        match = _OPEN_RE.fullmatch(normalized)
        if match:
            # Find the first non-None group
            url = next(g for g in match.groups() if g is not None).strip()
            return SkillMatch("browser", "open", {"url": url})
            
        match = _SEARCH_RE.fullmatch(normalized)
        if match:
            query = next(g for g in match.groups() if g is not None).strip()
            return SkillMatch("browser", "search", {"query": query})
            
        match = _CLICK_RE.fullmatch(normalized)
        if match:
            selector = next(g for g in match.groups() if g is not None).strip()
            return SkillMatch("browser", "click_element", {"selector": selector})
            
        match = _TYPE_RE.fullmatch(normalized)
        if match:
            return SkillMatch("browser", "type_in_field", {"text": match.group(1), "selector": match.group(2)})
            
        if _EXTRACT_RE.fullmatch(normalized):
            return SkillMatch("browser", "extract")
            
        if _SCREENSHOT_RE.fullmatch(normalized):
            return SkillMatch("browser", "screenshot")
            
        if _TAB_LIST_RE.fullmatch(normalized):
            return SkillMatch("browser", "tab_list")
            
        match = _TAB_CLOSE_RE.fullmatch(normalized)
        if match:
            tab_id = match.group(1)
            return SkillMatch("browser", "tab_close", {"tab_id": tab_id if tab_id else "current"})
            
        if _LAUNCH_RE.fullmatch(normalized):
            return SkillMatch("browser", "launch")
            
        if _CLOSE_RE.fullmatch(normalized):
            return SkillMatch("browser", "close_browser")
            
        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation == "open":
            url = str(params.get("url", "")).strip()
            if not url:
                raise ValueError("URL cannot be empty")
            return {"url": url}
            
        if operation == "search":
            query = str(params.get("query", "")).strip()
            if not query:
                raise ValueError("Search query cannot be empty")
            return {"query": query}
            
        if operation == "click_element":
            selector = str(params.get("selector", "")).strip()
            if not selector:
                raise ValueError("Selector cannot be empty")
            return {"selector": selector}
            
        if operation == "type_in_field":
            text = str(params.get("text", ""))
            selector = str(params.get("selector", "")).strip()
            if not text:
                raise ValueError("Text cannot be empty")
            if not selector:
                raise ValueError("Selector cannot be empty")
            return {"text": text, "selector": selector}
            
        if operation == "tab_close":
            tab_id = params.get("tab_id", "current")
            if tab_id != "current":
                try:
                    tab_id = int(tab_id)
                except ValueError:
                    raise ValueError("Invalid tab ID")
            return {"tab_id": tab_id}
            
        if operation in ("extract", "screenshot", "tab_list", "launch", "close_browser", "download"):
            return {}
            
        raise ValueError("Unknown browser operation")

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        try:
            if operation == "launch":
                result = self.engine.launch()
                return ExecutionResult(
                    success=result.success, 
                    message=result.message or (result.error if not result.success else ""), 
                    error=result.error
                )
                
            if operation == "close_browser":
                result = self.engine.close()
                return ExecutionResult(success=result.success, message=result.message, error=result.error)
                
            # Requires launched browser
            if not self.engine.is_launched and operation not in ("launch", "close_browser"):
                return ExecutionResult(False, "Browser is not launched", error="browser not launched")
                
            if operation == "open":
                result = self.navigator.open_url(params["url"])
                return ExecutionResult(success=result.success, message=result.message, error=result.error)
                
            if operation == "search":
                result = self.navigator.search_google(params["query"])
                return ExecutionResult(
                    success=result.success, 
                    message=result.message, 
                    data=result.data, 
                    error=result.error
                )
                
            if operation == "click_element":
                result = self.engine.click(params["selector"])
                return ExecutionResult(success=result.success, message=result.message, error=result.error)
                
            if operation == "type_in_field":
                result = self.engine.type_text(params["selector"], params["text"])
                return ExecutionResult(success=result.success, message=result.message, error=result.error)
                
            if operation == "extract":
                data = self.navigator.extract_page_data()
                return ExecutionResult(True, "Extracted page data", data=data)
                
            if operation == "screenshot":
                data = self.engine.screenshot()
                if not data:
                    return ExecutionResult(False, "Failed to take screenshot", error="screenshot failed")
                return ExecutionResult(True, "Screenshot captured", data={"bytes": data})
                
            if operation == "tab_list":
                tabs = self.engine.tabs()
                return ExecutionResult(True, f"Found {len(tabs)} tabs", data=tabs)
                
            if operation == "tab_close":
                tab_id = params["tab_id"]
                if tab_id == "current":
                    # This is simplified. Proper implementation would find active tab
                    tabs = self.engine.tabs()
                    active_tabs = [t for t in tabs if t.is_active]
                    if active_tabs:
                        result = self.engine.close_tab(active_tabs[0].tab_id)
                        return ExecutionResult(success=result.success, message=result.message, error=result.error)
                    return ExecutionResult(False, "No active tab found", error="no active tab")
                else:
                    result = self.engine.close_tab(tab_id)
                    return ExecutionResult(success=result.success, message=result.message, error=result.error)
                    
            return ExecutionResult(False, f"Unsupported operation: {operation}", error="unsupported operation")
            
        except Exception as e:
            return ExecutionResult(False, f"Browser operation failed: {str(e)}", error=str(e))
