from __future__ import annotations

import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core.memory_layers import (
    EpisodicMemory,
    ProceduralMemory,
    SemanticMemory,
    UnifiedMemory,
)


class TestLevel5AdvancedMemory(unittest.TestCase):
    def setUp(self):
        self.episodic = EpisodicMemory()
        self.semantic = SemanticMemory()
        self.procedural = ProceduralMemory()
        self.unified = UnifiedMemory()

    def test_episodic_memory_store_and_recall(self):
        ep1 = self.episodic.store_episode(
            summary="User requested weekly sales report generation",
            details={"client": "Acme Corp", "rows": 1500},
            outcome="success",
        )
        self.assertEqual(ep1.episode_id, "ep_1")

        ep2 = self.episodic.store_episode(
            summary="Attempted browser login to internal portal",
            details={"url": "https://intranet.example.com", "mfa_required": True},
            outcome="paused_for_auth",
        )
        self.assertEqual(ep2.episode_id, "ep_2")

        # Recall by query
        recalled = self.episodic.recall_episodes("sales report")
        self.assertEqual(len(recalled), 1)
        self.assertEqual(recalled[0]["details"]["client"], "Acme Corp")

        # Timeline
        timeline = self.episodic.get_timeline()
        self.assertEqual(len(timeline), 2)
        self.assertEqual(timeline[1]["outcome"], "paused_for_auth")

    def test_semantic_memory_facts_and_relationships(self):
        f1 = self.semantic.store_fact("User", "works_at", "DeepMind", confidence=0.95)
        self.assertEqual(f1.subject, "User")
        self.assertEqual(f1.predicate, "works_at")
        self.assertEqual(f1.object_, "DeepMind")

        f2 = self.semantic.store_fact("DeepMind", "located_in", "London", confidence=0.99)
        f3 = self.semantic.store_fact("User", "prefers_editor", "VSCode", confidence=1.0)

        # Query by subject
        user_facts = self.semantic.query_facts(subject="User")
        self.assertEqual(len(user_facts), 2)

        # Query by predicate
        location_facts = self.semantic.query_facts(predicate="located_in")
        self.assertEqual(len(location_facts), 1)
        self.assertEqual(location_facts[0]["object"], "London")

        # Related search
        related = self.semantic.find_related("DeepMind")
        self.assertEqual(len(related), 2)

    def test_procedural_memory_recipes_and_playbooks(self):
        steps = [
            {"step": 1, "action": "open_browser", "target": "https://github.com"},
            {"step": 2, "action": "navigate_repo", "target": "nexa"},
            {"step": 3, "action": "check_pull_requests"},
        ]
        proc = self.procedural.store_procedure(
            task_type="check_github_prs",
            steps=steps,
            prerequisites=["github_token_configured", "network_connected"],
            success_rate=1.0,
        )
        self.assertEqual(proc.task_type, "check_github_prs")

        # Recall
        recalled = self.procedural.recall_procedure("check_github_prs")
        self.assertIsNotNone(recalled)
        self.assertEqual(len(recalled["steps"]), 3)
        self.assertIn("github_token_configured", recalled["prerequisites"])

        # Multiple stores updates use_count
        self.procedural.store_procedure("check_github_prs", steps)
        recalled2 = self.procedural.recall_procedure("check_github_prs")
        self.assertEqual(recalled2["use_count"], 2)

    def test_unified_memory_10_layers_and_search(self):
        # Add items into different layers
        self.unified.conversation.add_turn("user", "Please remember my favorite database is PostgreSQL")
        self.unified.user_preferences.set_preference("database", "PostgreSQL")
        self.unified.episodic.store_episode("Installed PostgreSQL database on port 5432")
        self.unified.semantic.store_fact("PostgreSQL", "type", "relational database")
        self.unified.procedural.store_procedure("start_postgresql", [{"cmd": "pg_ctl start"}])

        snap = self.unified.snapshot()
        self.assertEqual(snap["episodic_count"], 1)
        self.assertEqual(snap["semantic_facts_count"], 1)
        self.assertEqual(snap["procedures_count"], 1)

        # Cross-layer unified search for "PostgreSQL"
        results = self.unified.unified_search("PostgreSQL")
        self.assertGreaterEqual(len(results["conversation"]), 1)
        self.assertGreaterEqual(len(results["preferences"]), 1)
        self.assertGreaterEqual(len(results["episodes"]), 1)
        self.assertGreaterEqual(len(results["facts"]), 1)
        self.assertGreaterEqual(len(results["procedures"]), 1)


if __name__ == "__main__":
    unittest.main()
