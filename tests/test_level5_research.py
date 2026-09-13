from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from research.contracts import ConfidenceLevel, ResearchReport, ResearchSource
from research.orchestrator import ResearchOrchestrator


class TestLevel5Research(unittest.TestCase):
    def setUp(self):
        self.orchestrator = ResearchOrchestrator()

    def test_query_decomposition(self):
        queries = self.orchestrator.decompose_query("Quantum Computing Security")
        self.assertEqual(len(queries), 3)
        self.assertTrue(any("overview" in q for q in queries))
        self.assertTrue(any("benchmarks" in q or "developments" in q for q in queries))
        self.assertTrue(any("challenges" in q or "comparison" in q for q in queries))

    def test_gather_sources_deduplication(self):
        # Provide search function returning duplicates
        def mock_search(q: str):
            return [
                {"url": "https://example.com/page1", "title": "Page 1", "snippet": "Text 1"},
                {"url": "https://example.com/page2", "title": "Page 2", "snippet": "Text 2"},
                {"url": "https://example.com/page1", "title": "Page 1 duplicate", "snippet": "Text 1"},
            ]

        orch = ResearchOrchestrator(search_fn=mock_search)
        sources = orch.gather_sources(["q1", "q2"])
        self.assertEqual(len(sources), 2)  # Only page1 and page2
        urls = [s.url for s in sources]
        self.assertEqual(urls, ["https://example.com/page1", "https://example.com/page2"])

    def test_extract_and_corroborate_confidence(self):
        sources = [
            ResearchSource(url="https://s1.org", title="Source 1", snippet="Fact A"),
            ResearchSource(url="https://s2.org", title="Source 2", snippet="Fact B"),
            ResearchSource(url="https://s3.org", title="Source 3", snippet="Fact C"),
        ]
        facts, conf = self.orchestrator.extract_and_corroborate(sources)
        self.assertEqual(len(facts), 3)
        self.assertEqual(conf, ConfidenceLevel.HIGH)

    def test_report_synthesis_markdown(self):
        sources = [
            ResearchSource(url="https://s1.org", title="Source 1", snippet="Foundations"),
            ResearchSource(url="https://s2.org", title="Source 2", snippet="Adoption"),
        ]
        facts, conf = self.orchestrator.extract_and_corroborate(sources)
        report = self.orchestrator.synthesize("Vector Databases", sources, facts, conf)

        self.assertEqual(report.topic, "Vector Databases")
        self.assertIn("Vector Databases", report.executive_summary)
        self.assertGreaterEqual(len(report.key_findings), 1)

        md = report.to_markdown()
        self.assertIn("# Research Report: Vector Databases", md)
        self.assertIn("## Executive Summary", md)
        self.assertIn("## Key Findings", md)
        self.assertIn("## References & Sources", md)
        self.assertIn("[Source 1](https://s1.org)", md)

    def test_end_to_end_conduct_research(self):
        report = self.orchestrator.conduct_research("Autonomous Computer Use Agents")
        self.assertEqual(report.topic, "Autonomous Computer Use Agents")
        self.assertEqual(report.confidence, ConfidenceLevel.HIGH)
        self.assertGreaterEqual(len(report.sources), 3)
        self.assertIn("Autonomous Computer Use Agents", report.to_markdown())


if __name__ == "__main__":
    unittest.main()
