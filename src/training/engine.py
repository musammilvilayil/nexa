from __future__ import annotations

from dataclasses import dataclass

from bridges import OllamaBridge, OllamaBridgeError

from .curriculum import TradingCurriculum
from .store import TrainingStore
from .trading_teacher import GeminiTradingTeacher, TradingLesson


@dataclass(frozen=True)
class ModuleTrainingResult:
    module_id: str
    mastered: bool
    attempts: int
    best_score: float
    reason: str


@dataclass(frozen=True)
class TrainingRunSummary:
    completed: bool
    modules: tuple[ModuleTrainingResult, ...]
    teacher_calls: int
    student_calls: int
    stopped_reason: str


class AutonomousTrainingEngine:
    """Bounded Gemini-teacher -> local-student curriculum loop.

    This trains reusable reasoning/knowledge through lessons and evaluations; it
    does not modify model weights. Budgets make the loop finite and auditable.
    Completion never changes the trading mode or enables a live broker.
    """

    ANSWER_SCHEMA = {
        "type": "object",
        "properties": {
            "answers": {"type": "array", "items": {"type": "integer"}},
        },
        "required": ["answers"],
    }

    def __init__(
        self,
        *,
        curriculum: TradingCurriculum | None = None,
        teacher: GeminiTradingTeacher | None = None,
        student: OllamaBridge | None = None,
        store: TrainingStore,
        max_attempts_per_module: int = 3,
        max_teacher_calls: int = 40,
        max_student_calls: int = 60,
    ) -> None:
        if max_attempts_per_module <= 0 or max_teacher_calls <= 0 or max_student_calls <= 0:
            raise ValueError("training budgets must be positive")
        self.curriculum = curriculum or TradingCurriculum()
        self.teacher = teacher or GeminiTradingTeacher()
        self.student = student or OllamaBridge()
        self.store = store
        self.max_attempts_per_module = int(max_attempts_per_module)
        self.max_teacher_calls = int(max_teacher_calls)
        self.max_student_calls = int(max_student_calls)

    def run(self, *, max_modules: int | None = None) -> TrainingRunSummary:
        if max_modules is not None and max_modules <= 0:
            raise ValueError("max_modules must be positive")
        teacher_calls = 0
        student_calls = 0
        results: list[ModuleTrainingResult] = []
        modules = self.curriculum.modules if max_modules is None else self.curriculum.modules[:max_modules]

        for module in modules:
            existing = self.store.progress(module.module_id)
            if existing and existing["mastered"]:
                results.append(
                    ModuleTrainingResult(
                        module.module_id,
                        True,
                        int(existing["attempts"]),
                        float(existing["best_score"]),
                        "already mastered",
                    )
                )
                continue

            if teacher_calls >= self.max_teacher_calls:
                return self._summary(results, teacher_calls, student_calls, "teacher call budget reached")
            if student_calls >= self.max_student_calls:
                return self._summary(results, teacher_calls, student_calls, "student call budget reached")

            module_attempts = 0
            best_score = float(existing["best_score"]) if existing else 0.0
            weakness_note: str | None = None
            mastered = False
            reason = "attempt budget exhausted"

            while module_attempts < self.max_attempts_per_module:
                if teacher_calls >= self.max_teacher_calls:
                    reason = "teacher call budget reached"
                    break
                if student_calls >= self.max_student_calls:
                    reason = "student call budget reached"
                    break

                previous_score = self.store.latest_score(module.module_id)
                lesson = self.teacher.teach(
                    module,
                    previous_score=previous_score,
                    weakness_note=weakness_note,
                )
                teacher_calls += 1
                lesson_id = self.store.save_lesson(lesson)

                answers = self._ask_student(lesson)
                student_calls += 1
                score, feedback, weakness_note = self._grade(lesson, answers)
                module_attempts += 1
                best_score = max(best_score, score)
                mastered = score >= module.minimum_score
                self.store.record_attempt(
                    module_id=module.module_id,
                    lesson_id=lesson_id,
                    score=score,
                    answers=answers,
                    feedback=feedback,
                    mastered=mastered,
                )

                if mastered:
                    reason = f"mastery threshold reached: {score:.2f} >= {module.minimum_score:.2f}"
                    break

            progress = self.store.progress(module.module_id)
            total_attempts = int(progress["attempts"]) if progress else module_attempts
            results.append(
                ModuleTrainingResult(
                    module.module_id,
                    mastered,
                    total_attempts,
                    best_score,
                    reason,
                )
            )
            if not mastered:
                return self._summary(results, teacher_calls, student_calls, reason)

        completed = len(results) == len(modules) and all(item.mastered for item in results)
        stopped = "curriculum complete" if completed else "training incomplete"
        return TrainingRunSummary(completed, tuple(results), teacher_calls, student_calls, stopped)

    def _ask_student(self, lesson: TradingLesson) -> tuple[int, ...]:
        lesson_text = self._student_material(lesson)
        result = self.student.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "You are NEXA's local STUDENT. Study the supplied trading-systems lesson and answer "
                        "the multiple-choice quiz using only zero-based choice indexes. Do not invent extra answers."
                    ),
                },
                {"role": "user", "content": lesson_text},
            ],
            schema=self.ANSWER_SCHEMA,
            think=False,
        )
        if not isinstance(result, dict):
            raise OllamaBridgeError("student did not return structured answers")
        raw_answers = result.get("answers")
        if not isinstance(raw_answers, list) or len(raw_answers) != len(lesson.quiz):
            raise OllamaBridgeError("student answer count does not match quiz")
        answers: list[int] = []
        for question, raw in zip(lesson.quiz, raw_answers):
            if isinstance(raw, bool) or not isinstance(raw, int):
                raise OllamaBridgeError("student answer indexes must be integers")
            if raw < 0 or raw >= len(question.choices):
                raise OllamaBridgeError("student answer index outside choices")
            answers.append(raw)
        return tuple(answers)

    @staticmethod
    def _student_material(lesson: TradingLesson) -> str:
        lines = [
            f"Lesson: {lesson.title}",
            lesson.summary,
            "",
            "Principles:",
            *[f"- {item}" for item in lesson.principles],
            "",
            "Hypothetical examples:",
            *[f"- {item}" for item in lesson.examples],
            "",
            "Safety notes:",
            *[f"- {item}" for item in lesson.safety_notes],
            "",
            "Quiz:",
        ]
        for index, question in enumerate(lesson.quiz):
            lines.append(f"Q{index + 1}. {question.question}")
            for choice_index, choice in enumerate(question.choices):
                lines.append(f"  {choice_index}: {choice}")
        lines.append("Return JSON with one zero-based answer index for each question, in order.")
        return "\n".join(lines)

    @staticmethod
    def _grade(
        lesson: TradingLesson,
        answers: tuple[int, ...],
    ) -> tuple[float, tuple[str, ...], str | None]:
        correct = 0
        feedback: list[str] = []
        weakness: list[str] = []
        for index, (question, answer) in enumerate(zip(lesson.quiz, answers), start=1):
            if answer == question.correct_index:
                correct += 1
                feedback.append(f"Q{index}: correct")
            else:
                feedback.append(f"Q{index}: incorrect - {question.explanation}")
                weakness.append(f"Question {index} concept: {question.question}")
        score = correct / len(lesson.quiz)
        weakness_note = "; ".join(weakness[:3]) if weakness else None
        return score, tuple(feedback), weakness_note

    @staticmethod
    def _summary(
        results: list[ModuleTrainingResult],
        teacher_calls: int,
        student_calls: int,
        reason: str,
    ) -> TrainingRunSummary:
        return TrainingRunSummary(False, tuple(results), teacher_calls, student_calls, reason)
