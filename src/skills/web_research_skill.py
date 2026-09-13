from __future__ import annotations

import re
from typing import Any, Mapping

from core.contracts import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata
from browser.browsercontrol_adapter import BrowserControlAdapter
from .google_search_skill import GoogleSearchSkill
from .web_navigation_skill import WebNavigationSkill

_RESEARCH_RE = re.compile(
    r"^(?:research\s+(?:about\s+)?['\"]?(.+?)['\"]?|"
    r"find\s+information\s+(?:about|on)\s+['\"]?(.+?)['\"]?|"
    r"summarize\s+topic\s+['\"]?(.+?)['\"]?)$",
    re.IGNORECASE,
)


class WebResearchSkill:
    """High-level autonomous web research composing search, navigation, extraction, and synthesis."""

    def __init__(
        self,
        adapter: BrowserControlAdapter | None = None,
        search_skill: GoogleSearchSkill | None = None,
        nav_skill: WebNavigationSkill | None = None,
    ) -> None:
        self.adapter = adapter
        self.search_skill = search_skill or GoogleSearchSkill(adapter)
        self.nav_skill = nav_skill or WebNavigationSkill(adapter)
        self.metadata = SkillMetadata(
            name="web_research",
            version="1.0.0",
            description="Autonomous web research, source extraction, and multi-source synthesis",
            operations=(
                OperationSpec("research", "Conduct end-to-end web research and synthesize findings", RiskTier.REMOTE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = text.strip().rstrip(".!?")
        m = _RESEARCH_RE.fullmatch(normalized)
        if m:
            topic = next(g for g in m.groups() if g is not None).strip()
            return SkillMatch("web_research", "research", {"topic": topic})
        return None

    def validate(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any]) -> Mapping[str, Any]:
        if operation == "research":
            topic = str(params.get("topic", "")).strip()
            if not topic:
                raise ValueError("Topic cannot be empty")
            return {"topic": topic}
        return {}

    def execute(self, operation: str, params: Mapping[str, Any], context: Mapping[str, Any]) -> ExecutionResult:
        if not self.adapter:
            return ExecutionResult(False, "BrowserControlAdapter not configured for WebResearchSkill")

        try:
            topic = params["topic"]

            # 1. Search Google
            search_res = self.search_skill.execute("search", {"query": topic}, context)
            if not search_res.success:
                return ExecutionResult(False, f"Research search failed: {search_res.error or search_res.message}")

            results = search_res.data.get("results", [])
            if not results:
                return ExecutionResult(True, f"No search results found for topic '{topic}'", data={"topic": topic, "sources": []})

            # 2. Pick top source and navigate
            top_source = results[0]
            top_url = top_source["url"]
            top_title = top_source.get("title", "")

            nav_res = self.nav_skill.execute("navigate", {"url": top_url}, context)
            if not nav_res.success:
                # Fallback to search snippets if navigation blocked
                summary = f"Summary of {topic} from search:\n" + "\n".join(
                    f"- {r.get('title')}: {r.get('snippet')} ({r.get('url')})" for r in results[:3]
                )
                return ExecutionResult(True, summary, data={"sources": results[:3], "fallback": True})

            # 3. Extract text content
            page_text = self.adapter.evaluate("""
            (() => {
                const article = document.querySelector('article, main, [role="main"]') || document.body;
                const paras = Array.from(article.querySelectorAll('p')).map(p => p.innerText.trim()).filter(t => t.length > 40);
                return paras.slice(0, 8).join('\\n\\n');
            })()
            """) or ""

            # 4. Synthesize answer with citations
            citations = [
                {"title": top_title, "url": top_url},
            ]
            for r in results[1:3]:
                citations.append({"title": r.get("title"), "url": r.get("url")})

            synthesis = (
                f"### Research Report: {topic}\n\n"
                f"**Primary Source:** [{top_title}]({top_url})\n\n"
                f"**Key Findings:**\n{page_text[:1500]}\n\n"
                f"**Citations:**\n" + "\n".join(f"- [{c['title']}]({c['url']})" for c in citations if c['title'])
            )

            return ExecutionResult(
                success=True,
                message=synthesis,
                data={
                    "topic": topic,
                    "primary_url": top_url,
                    "citations": citations,
                    "extracted_length": len(page_text),
                },
            )
        except Exception as exc:
            return ExecutionResult(False, f"WebResearch execution failed: {exc}", error=str(exc))
