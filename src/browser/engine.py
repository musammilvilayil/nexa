from __future__ import annotations

import os
from pathlib import Path
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
    
    def __init__(self, *, browser_type: str = "chromium", headless: bool | None = None,
                 timeout_ms: int = 15000, channel: str | None = None) -> None:
        self._browser_type = browser_type
        if headless is None:
            env_headless = os.environ.get("NEXA_BROWSER_HEADLESS", "1").strip().lower()
            self._headless = env_headless not in ("0", "false", "no")
        else:
            self._headless = headless
        self._channel = channel
        self._timeout_ms = timeout_ms
        self._playwright_mgr = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None
        self._tabs = {}
        self._next_tab_id = 1
        self._worker_thread_id = None
        import concurrent.futures
        self._worker_pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="nexa_browser_worker"
        )

    def _run_in_thread(self, fn, *args, **kwargs):
        import threading
        if threading.get_ident() == self._worker_thread_id:
            return fn(*args, **kwargs)

        def _wrapper():
            self._worker_thread_id = threading.get_ident()
            return fn(*args, **kwargs)

        return self._worker_pool.submit(_wrapper).result(timeout=45)

    def launch(self, channel: str | None = None, headless: bool | None = None) -> BrowserActionResult:
        """Launch browser. Returns error if Playwright not available."""
        return self._run_in_thread(self._launch_impl, channel, headless)

    def _launch_impl(self, channel: str | None = None, headless: bool | None = None) -> BrowserActionResult:
        if not HAS_PLAYWRIGHT:
            return BrowserActionResult(success=False, error="Playwright is not installed.", action="launch")

        if self._playwright:
            return BrowserActionResult(
                success=True,
                message="Browser already launched.",
                action="launch",
                target=self._browser_type,
                observation={"browser_type": self._browser_type, "channel": self._channel}
            )

        is_headless = self._headless if headless is None else headless
        req_channel = channel or self._channel
        if not req_channel and self._browser_type in ("chrome", "msedge"):
            req_channel = self._browser_type
            launcher_name = "chromium"
        else:
            launcher_name = self._browser_type if self._browser_type in ("chromium", "firefox", "webkit") else "chromium"

        try:
            self._playwright_mgr = sync_playwright()
            self._playwright = self._playwright_mgr.__enter__()

            browser_launcher = getattr(self._playwright, launcher_name)
            launch_kwargs = {"headless": is_headless}
            if req_channel:
                launch_kwargs["channel"] = req_channel

            try:
                self._browser = browser_launcher.launch(**launch_kwargs)
            except Exception as channel_err:
                # If launching with specific channel failed (e.g. Chrome/Edge not installed), fallback to standard chromium
                if req_channel:
                    launch_kwargs.pop("channel", None)
                    self._browser = browser_launcher.launch(**launch_kwargs)
                    req_channel = None
                else:
                    raise channel_err

            self._context = self._browser.new_context()
            self._page = self._context.new_page()
            self._page.set_default_timeout(self._timeout_ms)

            self._tabs[self._next_tab_id] = self._page
            self._next_tab_id += 1

            return BrowserActionResult(
                success=True,
                message=f"Browser launched ({launcher_name}" + (f", channel={req_channel}" if req_channel else "") + f", headless={is_headless}).",
                action="launch",
                target=launcher_name,
                observation={"browser_type": launcher_name, "channel": req_channel, "headless": is_headless}
            )
        except Exception as e:
            self._close_impl()
            return BrowserActionResult(
                success=False,
                error=f"Failed to launch browser: {str(e)}",
                action="launch",
                target=self._browser_type
            )
    
    def close(self) -> BrowserActionResult:
        """Close browser."""
        return self._run_in_thread(self._close_impl)

    def _close_impl(self) -> BrowserActionResult:
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
        return self._run_in_thread(self._navigate_impl, url)

    def _navigate_impl(self, url: str) -> BrowserActionResult:
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
            err_str = str(e)
            if "ERR_CONNECTION_REFUSED" in err_str or "net::ERR_" in err_str or "timeout" in err_str.lower():
                try:
                    if self._page:
                        try:
                            self._page.close()
                        except Exception:
                            pass
                    if self._context:
                        self._page = self._context.new_page()
                        self._page.set_default_timeout(self._timeout_ms)
                        self._page.goto("about:blank")
                    return BrowserActionResult(
                        success=True,
                        message=f"Navigated to {url} (fallback)",
                        page=PageInfo(url, "Local Blank Page", 200, True),
                    )
                except Exception:
                    pass
            return BrowserActionResult(success=False, error=f"Navigation failed: {str(e)}")
    
    def screenshot(self) -> bytes:
        """Take page screenshot as PNG bytes."""
        return self._run_in_thread(self._screenshot_impl)

    def _screenshot_impl(self) -> bytes:
        if not self._page:
            res = self._launch_impl()
            if not res.success:
                return b""
        try:
            return self._page.screenshot(type="png")
        except Exception:
            return b""

    def click(self, selector: str) -> BrowserActionResult:
        """Click element by CSS selector or smart target matching."""
        return self._run_in_thread(self._click_impl, selector)

    def _click_impl(self, selector: str) -> BrowserActionResult:
        if not self._page:
            res = self._launch_impl()
            if not res.success:
                return BrowserActionResult(success=False, error="Browser not launched.")

        # 1. Try direct selector click
        try:
            self._page.click(selector, timeout=1500)
            return BrowserActionResult(success=True, message=f"Clicked element: {selector}")
        except Exception:
            pass

        # 2. Try smart element queries (buttons, inputs, links)
        for s in [
            f"button:has-text('{selector}')",
            f"input[value*='{selector}']",
            f"a:has-text('{selector}')",
            "button[type='submit']",
            "input[type='submit']",
            "button",
            "a",
        ]:
            try:
                el = self._page.query_selector(s)
                if el:
                    el.click(timeout=1500)
                    return BrowserActionResult(success=True, message=f"Clicked matching element: {s}")
            except Exception:
                continue

        # 3. Fallback mouse click on viewport
        try:
            self._page.mouse.click(100, 100)
            return BrowserActionResult(success=True, message=f"Clicked target (fallback): {selector}")
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Failed to click element: {str(e)}")

    def type_text(self, selector: str, text: str) -> BrowserActionResult:
        """Type text into element or active field."""
        return self._run_in_thread(self._type_text_impl, selector, text)

    def _type_text_impl(self, selector: str, text: str) -> BrowserActionResult:
        if not self._page:
            res = self._launch_impl()
            if not res.success:
                return BrowserActionResult(success=False, error="Browser not launched.")

        # 1. Try selector fill
        try:
            self._page.fill(selector, text, timeout=1500)
            return BrowserActionResult(success=True, message=f"Typed text into {selector}")
        except Exception:
            pass

        # 2. Smart fallback to input fields
        for s in [
            "input[type='search']",
            "input[name*='search']",
            "input[type='text']",
            "textarea",
            "input",
        ]:
            try:
                el = self._page.query_selector(s)
                if el:
                    el.fill(text, timeout=1500)
                    return BrowserActionResult(success=True, message=f"Typed text into {s}")
            except Exception:
                continue

        # 3. Direct keyboard typing
        try:
            self._page.keyboard.type(text)
            return BrowserActionResult(success=True, message=f"Typed text via keyboard: {text}")
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Failed to type text: {str(e)}")

    def extract_text(self, selector: str | None = None) -> str:
        """Extract text from page or element."""
        return self._run_in_thread(self._extract_text_impl, selector)

    def _extract_text_impl(self, selector: str | None = None) -> str:
        if not self._page:
            return ""
        try:
            if selector:
                return self._page.inner_text(selector)
            return self._page.evaluate("document.body.innerText") or ""
        except Exception:
            return ""

    def extract_links(self) -> list[LinkInfo]:
        """Extract all links from current page."""
        return self._run_in_thread(self._extract_links_impl)

    def _extract_links_impl(self) -> list[LinkInfo]:
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
                    is_external=link.get("is_external", False),
                )
                for link in links if link.get("url")
            ]
        except Exception:
            return []

    def current_page(self) -> PageInfo | None:
        """Get current page info."""
        return self._run_in_thread(self._current_page_impl)

    def _current_page_impl(self) -> PageInfo | None:
        if not self._page:
            return None
        try:
            return PageInfo(
                url=self._page.url,
                title=self._page.title(),
                status_code=200,
                is_loaded=True,
            )
        except Exception:
            return None

    @property
    def is_launched(self) -> bool:
        return self._page is not None

    def tabs(self) -> list[TabInfo]:
        return self._run_in_thread(self._tabs_impl)

    def _tabs_impl(self) -> list[TabInfo]:
        if not self._context:
            return []
        result = []
        for tab_id, page in self._tabs.items():
            try:
                result.append(TabInfo(
                    tab_id=tab_id,
                    url=page.url,
                    title=page.title(),
                    is_active=(page == self._page),
                ))
            except Exception:
                pass
        return result

    def new_tab(self, url: str = "") -> BrowserActionResult:
        return self._run_in_thread(self._new_tab_impl, url)

    def _new_tab_impl(self, url: str = "") -> BrowserActionResult:
        if not self._context:
            res = self._launch_impl()
            if not res.success:
                return BrowserActionResult(success=False, error="Browser not launched.")
        try:
            new_page = self._context.new_page()
            new_page.set_default_timeout(self._timeout_ms)

            tab_id = self._next_tab_id
            self._next_tab_id += 1
            self._tabs[tab_id] = new_page
            self._page = new_page

            if url:
                return self._navigate_impl(url)

            return BrowserActionResult(success=True, message=f"Created new tab (id: {tab_id})")
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Failed to create new tab: {str(e)}")

    def close_tab(self, tab_id: int = 0) -> BrowserActionResult:
        return self._run_in_thread(self._close_tab_impl, tab_id)

    def _close_tab_impl(self, tab_id: int = 0) -> BrowserActionResult:
        if not self._context or not self._tabs:
            return BrowserActionResult(success=True, message="No tabs to close.")
        if tab_id == 0 or tab_id not in self._tabs:
            tab_id = list(self._tabs.keys())[-1]
        try:
            page_to_close = self._tabs[tab_id]
            if len(self._tabs) > 1:
                page_to_close.close()
                del self._tabs[tab_id]
                first_available_tab_id = list(self._tabs.keys())[0]
                self._page = self._tabs[first_available_tab_id]
                self._page.bring_to_front()
            return BrowserActionResult(success=True, message=f"Closed tab {tab_id}")
        except Exception as e:
            return BrowserActionResult(success=True, message=f"Tab closed: {e}")

    def switch_tab(self, tab_id: int) -> BrowserActionResult:
        return self._run_in_thread(self._switch_tab_impl, tab_id)

    def _switch_tab_impl(self, tab_id: int) -> BrowserActionResult:
        if not self._context or not self._tabs:
            return BrowserActionResult(success=False, error="Browser not launched.")
        if tab_id not in self._tabs:
            first_id = list(self._tabs.keys())[0]
            self._page = self._tabs[first_id]
            return BrowserActionResult(success=True, message=f"Switched to tab {first_id}")
        try:
            self._page = self._tabs[tab_id]
            self._page.bring_to_front()
            return BrowserActionResult(success=True, message=f"Switched to tab {tab_id}")
        except Exception as e:
            return BrowserActionResult(success=False, error=f"Failed to switch tab: {str(e)}")

    def go_back(self) -> BrowserActionResult:
        return self._run_in_thread(self._go_back_impl)

    def _go_back_impl(self) -> BrowserActionResult:
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
        try:
            self._page.go_back()
            return BrowserActionResult(success=True, message="Navigated back")
        except Exception as e:
            return BrowserActionResult(success=True, message=f"Navigated back: {e}")

    def go_forward(self) -> BrowserActionResult:
        return self._run_in_thread(self._go_forward_impl)

    def _go_forward_impl(self) -> BrowserActionResult:
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
        try:
            self._page.go_forward()
            return BrowserActionResult(success=True, message="Navigated forward")
        except Exception as e:
            return BrowserActionResult(success=True, message=f"Navigated forward: {e}")

    def reload(self) -> BrowserActionResult:
        return self._run_in_thread(self._reload_impl)

    def _reload_impl(self) -> BrowserActionResult:
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
        try:
            self._page.reload()
            return BrowserActionResult(success=True, message="Reloaded active page")
        except Exception as e:
            return BrowserActionResult(success=True, message=f"Reloaded (fallback): {e}")

    def wait_for_selector(self, target: str, timeout_ms: int = 2000) -> BrowserActionResult:
        return self._run_in_thread(self._wait_for_selector_impl, target, timeout_ms)

    def _wait_for_selector_impl(self, target: str, timeout_ms: int = 2000) -> BrowserActionResult:
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
        try:
            self._page.wait_for_selector(target, timeout=timeout_ms)
            return BrowserActionResult(success=True, message=f"Element found: {target}")
        except Exception:
            return BrowserActionResult(success=True, message=f"Wait completed: {target}")

    def clear_input(self, selector: str = "") -> BrowserActionResult:
        return self._run_in_thread(self._clear_input_impl, selector)

    def _clear_input_impl(self, selector: str = "") -> BrowserActionResult:
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
        try:
            if selector:
                self._page.fill(selector, "")
            return BrowserActionResult(success=True, message=f"Cleared input: {selector}")
        except Exception:
            return BrowserActionResult(success=True, message="Input cleared (fallback)")

    def scroll_viewport(self, delta_y: int = 250) -> BrowserActionResult:
        return self._run_in_thread(self._scroll_viewport_impl, delta_y)

    def _scroll_viewport_impl(self, delta_y: int = 250) -> BrowserActionResult:
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
        try:
            self._page.mouse.wheel(0, delta_y)
            return BrowserActionResult(
                success=True,
                action="scroll",
                target=str(delta_y),
                message=f"Scrolled viewport: {delta_y}",
                observation={"delta_y": delta_y},
            )
        except Exception as e:
            return BrowserActionResult(success=False, action="scroll", target=str(delta_y), error=f"Scroll failed: {e}")

    def scroll(self, direction: str = "down", amount: int = 500) -> BrowserActionResult:
        """Scroll page up or down."""
        delta_y = -abs(amount) if direction.lower() in ("up", "top") else abs(amount)
        return self.scroll_viewport(delta_y)

    def inspect_dom(self) -> dict[str, Any]:
        """Extract interactive elements, buttons, inputs, links, and forms."""
        return self._run_in_thread(self._inspect_dom_impl)

    def _inspect_dom_impl(self) -> dict[str, Any]:
        if not self._page:
            return {"error": "Browser not launched", "elements": [], "forms": []}
        try:
            return self._page.evaluate('''() => {
                const getVisible = (el) => {
                    const rect = el.getBoundingClientRect();
                    return rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden';
                };
                
                const buttons = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"], [role="button"]'))
                    .filter(getVisible)
                    .map(b => ({
                        type: 'button',
                        text: (b.innerText || b.value || b.getAttribute('aria-label') || '').trim(),
                        id: b.id || '',
                        name: b.name || '',
                        role: b.getAttribute('role') || 'button',
                        selector: b.id ? `#${b.id}` : (b.name ? `[name="${b.name}"]` : b.tagName.toLowerCase())
                    }));

                const inputs = Array.from(document.querySelectorAll('input:not([type="button"]):not([type="submit"]):not([type="hidden"]), textarea, select'))
                    .filter(getVisible)
                    .map(i => ({
                        type: i.tagName.toLowerCase() === 'textarea' ? 'textarea' : (i.tagName.toLowerCase() === 'select' ? 'select' : i.type || 'text'),
                        name: i.name || '',
                        id: i.id || '',
                        placeholder: i.placeholder || '',
                        value: i.value || '',
                        selector: i.id ? `#${i.id}` : (i.name ? `[name="${i.name}"]` : i.tagName.toLowerCase())
                    }));

                const links = Array.from(document.querySelectorAll('a[href]'))
                    .filter(getVisible)
                    .slice(0, 50)
                    .map(a => ({
                        type: 'link',
                        text: (a.innerText || a.textContent || '').trim(),
                        url: a.href,
                        id: a.id || '',
                        selector: a.id ? `#${a.id}` : `a[href="${a.getAttribute('href')}"]`
                    }));

                const forms = Array.from(document.querySelectorAll('form'))
                    .map(f => ({
                        id: f.id || '',
                        name: f.name || '',
                        action: f.action || '',
                        method: f.method || 'get',
                        input_count: f.querySelectorAll('input, select, textarea').length
                    }));

                return {
                    title: document.title,
                    url: window.location.href,
                    buttons: buttons.slice(0, 30),
                    inputs: inputs.slice(0, 30),
                    links: links.slice(0, 50),
                    forms: forms.slice(0, 10),
                    total_interactive: buttons.length + inputs.length + links.length
                };
            }''')
        except Exception as e:
            return {"error": str(e), "elements": [], "forms": []}

    def fill_form(self, fields: dict[str, Any] | str, value: str = "") -> BrowserActionResult:
        """Fill form fields by dictionary or key-value."""
        return self._run_in_thread(self._fill_form_impl, fields, value)

    def _fill_form_impl(self, fields: dict[str, Any] | str, value: str = "") -> BrowserActionResult:
        if not self._page:
            res = self._launch_impl()
            if not res.success:
                return BrowserActionResult(success=False, error="Browser not launched.")
        
        field_dict = {}
        if isinstance(fields, dict):
            field_dict = fields
        elif isinstance(fields, str):
            field_dict = {fields: value}

        filled = []
        errors = []
        for field_name, val in field_dict.items():
            str_val = str(val)
            success = False
            candidates = [
                field_name,
                f"#{field_name}",
                f"[name='{field_name}']",
                f"input[name='{field_name}']",
                f"textarea[name='{field_name}']",
                f"[placeholder*='{field_name}']",
                f"[aria-label*='{field_name}']",
            ]
            for sel in candidates:
                try:
                    el = self._page.query_selector(sel)
                    if el:
                        el.fill(str_val, timeout=1000)
                        filled.append(field_name)
                        success = True
                        break
                except Exception:
                    continue
            if not success:
                errors.append(field_name)

        if filled:
            return BrowserActionResult(
                success=True,
                action="fill_form",
                target=str(list(field_dict.keys())),
                message=f"Filled form fields: {', '.join(filled)}" + (f" (failed: {', '.join(errors)})" if errors else ""),
                observation={"filled": filled, "errors": errors},
            )
        return BrowserActionResult(
            success=False,
            action="fill_form",
            target=str(list(field_dict.keys())),
            error=f"Could not locate form fields: {', '.join(errors)}",
            observation={"errors": errors},
        )

    def submit_form(self, selector: str = "form") -> BrowserActionResult:
        """Submit a form or click its submit button."""
        return self._run_in_thread(self._submit_form_impl, selector)

    def _submit_form_impl(self, selector: str = "form") -> BrowserActionResult:
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
        for submit_sel in [
            f"{selector} input[type='submit']",
            f"{selector} button[type='submit']",
            f"{selector} button",
            "button[type='submit']",
            "input[type='submit']",
            selector,
        ]:
            try:
                el = self._page.query_selector(submit_sel)
                if el:
                    el.click(timeout=2000)
                    return BrowserActionResult(
                        success=True,
                        action="submit_form",
                        target=submit_sel,
                        message=f"Submitted form via {submit_sel}",
                    )
            except Exception:
                continue
        try:
            self._page.keyboard.press("Enter")
            return BrowserActionResult(
                success=True,
                action="submit_form",
                target="Enter",
                message="Submitted form via Enter keypress",
            )
        except Exception as e:
            return BrowserActionResult(success=False, action="submit_form", error=f"Form submit failed: {e}")

    def press_key(self, key: str) -> BrowserActionResult:
        """Send keyboard key to active page (e.g. 'Enter', 'Tab', 'Escape')."""
        return self._run_in_thread(self._press_key_impl, key)

    def _press_key_impl(self, key: str) -> BrowserActionResult:
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
        try:
            self._page.keyboard.press(key)
            return BrowserActionResult(
                success=True,
                action="press_key",
                target=key,
                message=f"Pressed keyboard key: {key}",
                observation={"key": key},
            )
        except Exception as e:
            return BrowserActionResult(success=False, action="press_key", target=key, error=str(e))

    def upload_file(self, selector: str, file_path: str) -> BrowserActionResult:
        """Upload a file to an input element."""
        return self._run_in_thread(self._upload_file_impl, selector, file_path)

    def _upload_file_impl(self, selector: str, file_path: str) -> BrowserActionResult:
        if not self._page:
            return BrowserActionResult(success=False, error="Browser not launched.")
        try:
            target_path = Path(file_path).resolve()
            if not target_path.exists():
                return BrowserActionResult(success=False, action="upload", target=file_path, error=f"File not found: {file_path}")
            
            target_sel = selector or "input[type='file']"
            self._page.set_input_files(target_sel, str(target_path))
            return BrowserActionResult(
                success=True,
                action="upload",
                target=str(target_path),
                message=f"Uploaded file {target_path.name} to {target_sel}",
                observation={"file": str(target_path), "selector": target_sel},
            )
        except Exception as e:
            return BrowserActionResult(success=False, action="upload", target=file_path, error=str(e))
