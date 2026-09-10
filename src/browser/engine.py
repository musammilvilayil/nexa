from __future__ import annotations

from typing import Any

from .contracts import BrowserActionResult, LinkInfo, PageInfo, TabInfo

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError
    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False
    sync_playwright = None
    PlaywrightTimeoutError = Exception
    PlaywrightError = Exception

class BrowserEngine:
    """Playwright-based browser automation engine.
    
    Gracefully handles Playwright not being installed.
    All operations are synchronous (uses sync_playwright).
    """
    
    def __init__(self, *, browser_type: str = "chromium", headless: bool = False,
                 timeout_ms: int = 30000) -> None:
        self._browser_type = browser_type
        self._headless = headless
        self._timeout_ms = timeout_ms
        self._playwright_mgr = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._tabs = {}
        self._next_tab_id = 1
    
    def launch(self) -> BrowserActionResult:
        """Launch browser. Returns error if Playwright not available."""
        if not HAS_PLAYWRIGHT:
            return BrowserActionResult(success=False, error="Playwright is not installed.")
        
        if self._playwright:
            return BrowserActionResult(success=True, message="Browser already launched.")
            
        try:
            self._playwright_mgr = sync_playwright()
            self._playwright = self._playwright_mgr.__enter__()
            
            browser_launcher = getattr(self._playwright, self._browser_type)
            self._browser = browser_launcher.launch(headless=self._headless)
            self._context = self._browser.new_context()
            self._page = self._context.new_page()
            self._page.set_default_timeout(self._timeout_ms)
            
            self._tabs[self._next_tab_id] = self._page
            self._next_tab_id += 1
            
            return BrowserActionResult(success=True, message="Browser launched.")
        except Exception as e:
            self.close()
            return BrowserActionResult(success=False, error=f"Failed to launch browser: {str(e)}")
    
    def close(self) -> BrowserActionResult:
        """Close browser."""
        try:
            if self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
            if self._playwright_mgr:
                self._playwright_mgr.__exit__(None, None, None)
        except Exception:
            pass
        finally:
            self._playwright_mgr = None
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None
            self._tabs.clear()
            self._next_tab_id = 1
            
        return BrowserActionResult(success=True, message="Browser closed.")
    
    def navigate(self, url: str) -> BrowserActionResult:
        """Navigate to URL."""
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
            
        try:
            response = self._page.goto(url)
            status_code = response.status if response else 200
            
            # Wait for load state to ensure it's ready
            self._page.wait_for_load_state("domcontentloaded")
            
            page_info = self.current_page()
            if page_info:
                # Update status code based on response
                page_info = PageInfo(
                    url=page_info.url,
                    title=page_info.title,
                    status_code=status_code,
                    is_loaded=True
                )
            
            return BrowserActionResult(success=True, message=f"Navigated to {url}", page=page_info)
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Navigation failed: {str(e)}")
    
    def screenshot(self) -> bytes:
        """Take page screenshot as PNG bytes."""
        if not self._page:
            return b""
            
        try:
            return self._page.screenshot(type="png")
        except Exception:
            return b""
    
    def click(self, selector: str) -> BrowserActionResult:
        """Click element by CSS selector."""
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
            
        try:
            self._page.click(selector)
            return BrowserActionResult(success=True, message=f"Clicked element: {selector}")
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Failed to click element: {str(e)}")
    
    def type_text(self, selector: str, text: str) -> BrowserActionResult:
        """Type text into element by CSS selector."""
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
            
        try:
            self._page.fill(selector, text)
            return BrowserActionResult(success=True, message=f"Typed text into {selector}")
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Failed to type text: {str(e)}")
    
    def extract_text(self, selector: str | None = None) -> str:
        """Extract text from page or element."""
        if not self._page:
            return ""
            
        try:
            if selector:
                return self._page.inner_text(selector)
            return self._page.evaluate("document.body.innerText")
        except Exception:
            return ""
    
    def extract_links(self) -> list[LinkInfo]:
        """Extract all links from current page."""
        if not self._page:
            return []
            
        try:
            links = self._page.evaluate('''
                Array.from(document.querySelectorAll('a')).map(a => ({
                    text: a.innerText || a.textContent,
                    url: a.href,
                    is_external: a.host !== window.location.host
                }))
            ''')
            
            return [
                LinkInfo(
                    text=link.get("text", "").strip(),
                    url=link.get("url", ""),
                    is_external=link.get("is_external", False)
                ) 
                for link in links if link.get("url")
            ]
        except Exception:
            return []
    
    def current_page(self) -> PageInfo | None:
        """Get current page info."""
        if not self._page:
            return None
            
        try:
            return PageInfo(
                url=self._page.url,
                title=self._page.title(),
                status_code=200,  # Playwright doesn't easily surface this after navigation
                is_loaded=True
            )
        except Exception:
            return None
    
    @property
    def is_launched(self) -> bool:
        return self._page is not None
    
    def tabs(self) -> list[TabInfo]:
        if not self._context:
            return []
            
        result = []
        for tab_id, page in self._tabs.items():
            try:
                result.append(TabInfo(
                    tab_id=tab_id,
                    url=page.url,
                    title=page.title(),
                    is_active=(page == self._page)
                ))
            except Exception:
                pass
                
        return result
        
    def new_tab(self, url: str = "") -> BrowserActionResult:
        if not self._context:
            return BrowserActionResult(success=False, error="Browser not launched.")
            
        try:
            new_page = self._context.new_page()
            new_page.set_default_timeout(self._timeout_ms)
            
            tab_id = self._next_tab_id
            self._next_tab_id += 1
            self._tabs[tab_id] = new_page
            
            self._page = new_page
            
            if url:
                return self.navigate(url)
                
            return BrowserActionResult(success=True, message=f"Created new tab (id: {tab_id})")
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Failed to create new tab: {str(e)}")
            
    def close_tab(self, tab_id: int) -> BrowserActionResult:
        if not self._context:
            return BrowserActionResult(success=False, error="Browser not launched.")
            
        if tab_id not in self._tabs:
            return BrowserActionResult(success=False, error=f"Tab {tab_id} not found.")
            
        try:
            page_to_close = self._tabs[tab_id]
            
            # Don't close the only tab
            if len(self._tabs) <= 1:
                return BrowserActionResult(success=False, error="Cannot close the only tab.")
                
            page_to_close.close()
            del self._tabs[tab_id]
            
            # If we closed the active tab, switch to another one
            if self._page == page_to_close:
                # Just pick the first available tab
                first_available_tab_id = list(self._tabs.keys())[0]
                self._page = self._tabs[first_available_tab_id]
                self._page.bring_to_front()
                
            return BrowserActionResult(success=True, message=f"Closed tab {tab_id}")
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Failed to close tab: {str(e)}")
            
    def switch_tab(self, tab_id: int) -> BrowserActionResult:
        if not self._context:
            return BrowserActionResult(success=False, error="Browser not launched.")
            
        if tab_id not in self._tabs:
            return BrowserActionResult(success=False, error=f"Tab {tab_id} not found.")
            
        try:
            self._page = self._tabs[tab_id]
            self._page.bring_to_front()
            return BrowserActionResult(success=True, message=f"Switched to tab {tab_id}")
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Failed to switch tab: {str(e)}")
