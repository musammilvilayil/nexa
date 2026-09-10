from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class ResearchSource:
    url: str
    title: str
    snippet: str
    accessed_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reliability_score: float = 0.9


@dataclass(frozen=True)
class ResearchFact:
    statement: str
    sources: tuple[str, ...]
    corroborated: bool = True
    conflicts: tuple[str, ...] = ()


@dataclass
class ResearchReport:
    topic: str
    executive_summary: str
    key_findings: list[str] = field(default_factory=list)
    subtopics: dict[str, str] = field(default_factory=dict)
    sources: list[ResearchSource] = field(default_factory=list)
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_markdown(self) -> str:
        lines = [
            f"# Research Report: {self.topic}",
            "",
            f"**Confidence Level:** {self.confidence.value.upper()}",
            f"**Generated:** {self.created_at}",
            "",
            "## Executive Summary",
            self.executive_summary,
            "",
            "## Key Findings",
        ]
        for f in self.key_findings:
            lines.append(f"- {f}")
        lines.append("")

        if self.subtopics:
            lines.append("## Detailed Analysis")
            for sub, detail in self.subtopics.items():
                lines.append(f"### {sub}")
                lines.append(detail)
                lines.append("")

        lines.append("## References & Sources")
        for idx, s in enumerate(self.sources, 1):
            lines.append(f"{idx}. [{s.title}]({s.url}) — {s.snippet}")
        lines.append("")

        return "\n".join(lines)
