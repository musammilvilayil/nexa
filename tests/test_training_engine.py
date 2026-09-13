import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from sandbox import SandboxResult
from training import (
    AutonomousTrainingEngine,
    CurriculumModule,
    SkillForge,
    TradingCurriculum,
    TradingLesson,
    TrainingStore,
)
from training.trading_teacher import QuizQuestion


class FakeTeacher:
    def __init__(self):
        self.calls = 0

    def teach(self, module, previous_score=None, weakness_note=None):
        self.calls += 1
        quiz = tuple(
            QuizQuestion(
                question=f"Q{index}",
                choices=("wrong", "correct", "other", "other2"),
                correct_index=1,
                explanation="choice 1 follows the risk rule",
            )
            for index in range(5)
        )
        return TradingLesson(
            module_id=module.module_id,
            title=module.title,
            summary="Risk controls dominate desired profit.",
            principles=("Use bounded risk.",),
            examples=("Hypothetical example.",),
            safety_notes=("Never bypass the risk engine.",),
            quiz=quiz,
            provider="fake",
        )


class FakeStudent:
    def __init__(self, answers):
        self.answers = answers
        self.calls = 0

    def chat(self, messages, schema=None, think=False):
        self.calls += 1
        return {"answers": list(self.answers)}


class FakeForgeBridge:
    model = "fake"

    def generate_json(self, prompt, schema, system_instruction=None):
        return {
            "name": "echo",
            "description": "safe echo skill",
            "skill_py": (
                "from core import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata\n\n"
                "class EchoSkill:\n"
                "    def __init__(self):\n"
                "        self.metadata = SkillMetadata('echo','0.1','echo',(OperationSpec('echo','echo',RiskTier.READ),))\n"
                "    def match(self, text, context):\n"
                "        return SkillMatch('echo','echo',{'text': text[5:]}) if text.startswith('echo ') else None\n"
                "    def validate(self, operation, params, context):\n"
                "        value = str(params.get('text','')).strip()\n"
                "        if not value: raise ValueError('text required')\n"
                "        return {'text': value}\n"
                "    def execute(self, operation, params, context):\n"
                "        return ExecutionResult(True, params['text'])\n"
            ),
            "test_skill_py": (
                "import unittest\n"
                "from skill import EchoSkill\n\n"
                "class T(unittest.TestCase):\n"
                "    def test_echo(self):\n"
                "        self.assertEqual(EchoSkill().execute('echo', {'text':'x'}, {}).message, 'x')\n"
            ),
            "intents": ["echo hello", "ith echo cheyyu"],
            "teacher_notes": "narrow read-only candidate",
        }


class FakeSandbox:
    def run(self, files):
        return SandboxResult(True, True, True, None, (), "tests passed")


class TrainingTests(unittest.TestCase):
    def test_training_engine_marks_module_mastered_with_deterministic_grade(self):
        module = CurriculumModule(
            "risk",
            "Risk",
            "Learn risk",
            ("position sizing",),
            "Do not bypass risk.",
            minimum_score=0.8,
        )
        curriculum = TradingCurriculum((module,))
        with tempfile.TemporaryDirectory() as temp:
            store = TrainingStore(Path(temp) / "training.db")
            engine = AutonomousTrainingEngine(
                curriculum=curriculum,
                teacher=FakeTeacher(),
                student=FakeStudent((1, 1, 1, 1, 1)),
                store=store,
                max_attempts_per_module=2,
                max_teacher_calls=2,
                max_student_calls=2,
            )
            summary = engine.run()
            self.assertTrue(summary.completed)
            self.assertEqual(summary.modules[0].best_score, 1.0)
            self.assertTrue(store.progress("risk")["mastered"])

    def test_training_engine_stops_after_bounded_failed_attempts(self):
        module = CurriculumModule(
            "risk",
            "Risk",
            "Learn risk",
            ("position sizing",),
            "Do not bypass risk.",
            minimum_score=0.8,
        )
        with tempfile.TemporaryDirectory() as temp:
            store = TrainingStore(Path(temp) / "training.db")
            engine = AutonomousTrainingEngine(
                curriculum=TradingCurriculum((module,)),
                teacher=FakeTeacher(),
                student=FakeStudent((0, 0, 0, 0, 0)),
                store=store,
                max_attempts_per_module=2,
                max_teacher_calls=2,
                max_student_calls=2,
            )
            summary = engine.run()
            self.assertFalse(summary.completed)
            self.assertEqual(summary.teacher_calls, 2)
            self.assertEqual(summary.student_calls, 2)
            self.assertEqual(store.progress("risk")["attempts"], 2)

    def test_skill_forge_returns_candidate_but_does_not_promote_it(self):
        forge = SkillForge(
            bridge=FakeForgeBridge(),
            sandbox=FakeSandbox(),
            max_repairs=0,
        )
        result = forge.forge("echo a validated string", risk_tier="read")
        self.assertTrue(result.passed)
        self.assertEqual(result.candidate.name, "echo")
        self.assertIn("promotion", result.reason)


if __name__ == "__main__":
    unittest.main()
