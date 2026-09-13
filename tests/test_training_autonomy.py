import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from training import (
    AutonomousLearningSupervisor,
    CandidateStore,
    CurriculumModule,
    ImprovementBacklog,
    SkillCandidate,
    TradingCurriculum,
)


class FakeProgressStore:
    def __init__(self):
        self.state = {}

    def progress(self, module_id):
        return self.state.get(module_id)

    def mark(self, module_id, *, mastered, attempts=1, best_score=1.0):
        self.state[module_id] = {
            "module_id": module_id,
            "mastered": mastered,
            "attempts": attempts,
            "best_score": best_score,
        }


class FakeEngine:
    def __init__(self, curriculum, store, *, master=True):
        self.curriculum = curriculum
        self.store = store
        self.master = master

    def run(self):
        module = self.curriculum.modules[0]
        previous = self.store.progress(module.module_id)
        attempts = 1 if previous is None else previous["attempts"] + 1
        self.store.mark(
            module.module_id,
            mastered=self.master,
            attempts=attempts,
            best_score=1.0 if self.master else 0.25,
        )
        return SimpleNamespace(teacher_calls=1, student_calls=1)


class FakeForge:
    def __init__(self, candidate):
        self.candidate = candidate
        self.calls = []

    def forge(self, capability_request, *, risk_tier, context=None):
        self.calls.append((capability_request, risk_tier, context))
        return SimpleNamespace(
            passed=True,
            candidate=self.candidate,
            reason="passed",
        )


class AutonomousLearningTests(unittest.TestCase):
    def _curriculum(self):
        return TradingCurriculum(
            (
                CurriculumModule("one", "One", "Learn one", ("a",), "safe"),
                CurriculumModule("two", "Two", "Learn two", ("b",), "safe"),
            )
        )

    def test_supervisor_advances_until_all_modules_mastered(self):
        store = FakeProgressStore()
        curriculum = self._curriculum()

        def builder(selected, teacher_budget, student_budget):
            self.assertGreater(teacher_budget, 0)
            self.assertGreater(student_budget, 0)
            return FakeEngine(selected, store, master=True)

        supervisor = AutonomousLearningSupervisor(
            curriculum=curriculum,
            store=store,
            engine_builder=builder,
            max_module_rounds=5,
            max_teacher_calls=10,
            max_student_calls=10,
            max_forge_items=0,
        )
        summary = supervisor.run()

        self.assertTrue(summary.curriculum_complete)
        self.assertEqual(summary.module_rounds, 2)
        self.assertEqual(summary.teacher_calls, 2)
        self.assertEqual(summary.student_calls, 2)
        self.assertTrue(store.progress("one")["mastered"])
        self.assertTrue(store.progress("two")["mastered"])

    def test_retry_limit_stops_persistent_learning_failure(self):
        store = FakeProgressStore()
        curriculum = TradingCurriculum(
            (CurriculumModule("hard", "Hard", "Learn hard", ("x",), "safe"),)
        )

        def builder(selected, teacher_budget, student_budget):
            return FakeEngine(selected, store, master=False)

        supervisor = AutonomousLearningSupervisor(
            curriculum=curriculum,
            store=store,
            engine_builder=builder,
            max_module_rounds=10,
            max_rounds_per_module=2,
            max_teacher_calls=10,
            max_student_calls=10,
            max_forge_items=0,
        )
        summary = supervisor.run()

        self.assertFalse(summary.curriculum_complete)
        self.assertEqual(summary.module_rounds, 2)
        self.assertIn("retry limit", summary.stopped_reason)

    def test_queued_gap_is_forged_and_staged_not_runtime_registered(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            db = root / "training.db"
            backlog = ImprovementBacklog(db)
            backlog.enqueue(
                "summarize a completed backtest report",
                risk_tier="read",
                context="trading research only",
            )
            candidate = SkillCandidate(
                name="backtest_reporter",
                description="Read-only backtest report helper",
                risk_tier="read",
                skill_py="VALUE = 1\n",
                test_skill_py="import unittest\n\nclass T(unittest.TestCase):\n    def test_ok(self):\n        self.assertTrue(True)\n",
                intents_json='["summarize backtest"]',
                teacher_notes="generated for test",
            )
            forge = FakeForge(candidate)
            candidate_store = CandidateStore(root / "candidates")
            store = FakeProgressStore()
            curriculum = TradingCurriculum(
                (CurriculumModule("done", "Done", "Done", ("x",), "safe"),)
            )
            store.mark("done", mastered=True)

            def builder(selected, teacher_budget, student_budget):
                raise AssertionError("engine should not run for mastered curriculum")

            supervisor = AutonomousLearningSupervisor(
                curriculum=curriculum,
                store=store,
                engine_builder=builder,
                backlog=backlog,
                skill_forge=forge,
                candidate_store=candidate_store,
                max_forge_items=2,
            )
            summary = supervisor.run()

            self.assertTrue(summary.curriculum_complete)
            self.assertEqual(summary.forged, 1)
            self.assertEqual(summary.staged, 1)
            staged = list((root / "candidates" / "backtest_reporter").iterdir())
            self.assertEqual(len(staged), 1)
            manifest = json.loads((staged[0] / "manifest.json").read_text(encoding="utf-8"))
            self.assertFalse(manifest["runtime_registered"])
            self.assertTrue(manifest["promotion_required"])
            self.assertEqual(backlog.pending(), ())

    def test_candidate_store_rejects_unsafe_generated_name(self):
        with tempfile.TemporaryDirectory() as temp:
            store = CandidateStore(Path(temp))
            candidate = SkillCandidate(
                name="../escape",
                description="bad",
                risk_tier="read",
                skill_py="VALUE = 1\n",
                test_skill_py="",
                intents_json="[]",
                teacher_notes="",
            )
            with self.assertRaises(ValueError):
                store.stage(candidate)


if __name__ == "__main__":
    unittest.main()
