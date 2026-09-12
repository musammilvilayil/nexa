from __future__ import annotations

import urllib.parse
from typing import Any

from .contracts import BrowserActionResult
from .engine import BrowserEngine

class WebNavigator:
    """High-level web navigation with intent understanding."""
    
    def __init__(self, engine: BrowserEngine) -> None:
        self._engine = engine
    
    def search_google(self, query: str) -> BrowserActionResult:
        """Search Google and return results."""
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://www.google.com/search?q={encoded_query}"
        
        result = self._engine.navigate(url)
        if not result.success:
            return result
            
        # Wait a bit for results to load then extract text (simplified)
        text = self._engine.extract_text()
        return BrowserActionResult(
            success=True,
            message=f"Searched Google for '{query}'",
            data={"text": text[:1000] + "..." if len(text) > 1000 else text}
        )
    
    def open_url(self, url: str) -> BrowserActionResult:
        """Navigate to URL with protocol validation."""
        clean_url = url.strip()
        if not (clean_url.startswith("http://") or clean_url.startswith("https://")):
            clean_url = f"https://{clean_url}"
            
        return self._engine.navigate(clean_url)
    
    def extract_page_data(self) -> dict[str, Any]:
        """Extract structured data from current page."""
        page_info = self._engine.current_page()
        if not page_info:
            return {}
            
        return {
            "title": page_info.title,
            "url": page_info.url,
            "text": self._engine.extract_text(),
            "links": [
                {"text": link.text, "url": link.url, "external": link.is_external}
                for link in self._engine.extract_links()
            ][:50]  # Limit to first 50 links
        }
    
    def scroll_page(self, direction: str = "down", amount: int = 3) -> BrowserActionResult:
        """Scroll page up or down."""
        # Simplified scroll implementation - in a real app this would use JS execution
        if not self._engine.is_launched:
            return BrowserActionResult(success=False, error="Browser not launched.")
            
        try:
            if hasattr(self._engine, "_page") and self._engine._page:
                scroll_amount = amount * 500
                if direction.lower() == "up":
                    scroll_amount = -scroll_amount
                    
                self._engine._page.evaluate(f"window.scrollBy(0, {scroll_amount})")
                return BrowserActionResult(success=True, message=f"Scrolled {direction}")
            return BrowserActionResult(success=False, error="Cannot scroll, page not available.")
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Failed to scroll: {str(e)}")

    def click_first_result(self) -> BrowserActionResult:
        """Click the first non-ad search result."""
        if not self._engine.is_launched:
            return BrowserActionResult(success=False, error="Browser not launched.")
        links = self._engine.extract_links()
        for link in links:
            u = link.url.lower()
            if "google.com" not in u and (u.startswith("http://") or u.startswith("https://")):
                return self.open_url(link.url)
        for sel in ("a:has(h3)", "div.g a", "#search a"):
            res = self._engine.click(sel)
            if res.success:
                return res
        return BrowserActionResult(success=False, error="No search result link found")
