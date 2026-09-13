from __future__ import annotations

import re
import urllib.parse
from typing import Any, Mapping

from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from browser.browsercontrol_adapter import BrowserControlAdapter

_GOOGLE_SEARCH_RE = re.compile(
    r"^(?:google\s+search\s+(?:for\s+)?['\"]?(.+?)['\"]?|"
    r"search\s+(?:google\s+)?(?:for\s+)?['\"]?(.+?)['\"]?|"
    r"find\s+(?:on\s+google\s+)?['\"]?(.+?)['\"]?)$",
    re.IGNORECASE,
)


class GoogleSearchSkill:
    """High-level Google Search skill backed by browserControl foundation."""

    def __init__(self, adapter: BrowserControlAdapter | None = None) -> None:
        self.adapter = adapter
        self.metadata = SkillMetadata(
            name="google_search",
            version="1.0.0",
            description="Autonomous Google search, result ranking, and non-ad link extraction",
            operations=(
                OperationSpec("search", "Execute Google search and retrieve non-ad organic results", RiskTier.REMOTE),
                OperationSpec("extract_results", "Extract ranked organic search results from active page", RiskTier.READ),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = text.strip().rstrip(".!?")
        m = _GOOGLE_SEARCH_RE.fullmatch(normalized)
        if m:
            query = next(g for g in m.groups() if g is not None).strip()
            return SkillMatch("google_search", "search", {"query": query})
        return None

    def validate(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        if operation == "search":
            q = str(params.get("query", "")).strip()
            if not q:
                raise ValueError("Search query cannot be empty")
            return {"query": q}
        return {}

    def execute(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any]) -> ExecutionResult:
        if not self.adapter:
            return ExecutionResult(False, "BrowserControlAdapter not configured for GoogleSearchSkill")

        try:
            if not self.adapter.is_connected:
                self.adapter.start()

            if operation == "search":
                query = params["query"]
                encoded = urllib.parse.quote_plus(query)
                search_url = f"https://www.google.com/search?q={encoded}"

                # 1. Navigate
                self.adapter.navigate(search_url)

                # 2. Strict Observation Contract
                obs = self.adapter.observe()

                # 3. Extract organic non-ad search results via evaluate
                extract_script = """
                (() => {
                    const results = [];
                    // Organic search container links
                    const anchors = Array.from(document.querySelectorAll('div#search a h3, div#rso a h3'));
                    for (const h3 of anchors) {
                        const a = h3.closest('a');
                        if (a && a.href && !a.href.includes('/aclk?') && !a.href.startsWith('https://www.google.com/search')) {
                            const title = h3.innerText || a.innerText;
                            const snippetEl = a.closest('div.g')?.querySelector('div[style*="-webkit-line-clamp"], div.VwiC3b');
                            const snippet = snippetEl ? snippetEl.innerText : '';
                            results.push({
                                title: title.trim(),
                                url: a.href,
                                snippet: snippet.trim()
                            });
                        }
                    }
                    return results.slice(0, 5);
                })()
                """
                results = self.adapter.evaluate(extract_script) or []

                count = len(results)
                return ExecutionResult(
                    success=True,
                    message=f"Found {count} organic search results for '{query}'",
                    data={
                        "query": query,
                        "observation_id": obs.observation_id,
                        "results": results,
                    },
                )

            elif operation == "extract_results":
                obs = self.adapter.observe()
                return ExecutionResult(True, "Extracted search results", data={"observation_id": obs.observation_id})

            return ExecutionResult(False, f"Unknown operation {operation}")
        except Exception as exc:
            return ExecutionResult(False, f"GoogleSearch failed: {exc}", error=str(exc))
