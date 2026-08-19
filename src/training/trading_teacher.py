from __future__ import annotations

from dataclasses import dataclass

from bridges import GeminiBridge

from .curriculum import CurriculumModule


@dataclass(frozen=True)
class QuizQuestion:
    question: str
    choices: tuple[str, ...]
    correct_index: int
    explanation: str

    def __post_init__(self) -> None:
        if not self.question.strip() or len(self.choices) < 2:
            raise ValueError("quiz question requires text and at least two choices")
        if not 0 <= self.correct_index < len(self.choices):
            raise ValueError("correct_index outside choices")


@dataclass(frozen=True)
class TradingLesson:
    module_id: str
    title: str
    summary: str
    principles: tuple[str, ...]
    examples: tuple[str, ...]
    safety_notes: tuple[str, ...]
    quiz: tuple[QuizQuestion, ...]
    provider: str

    def __post_init__(self) -> None:
        if not self.module_id.strip() or not self.title.strip() or not self.summary.strip():
            raise ValueError("lesson identity and summary are required")
        if not self.principles or not self.quiz:
            raise ValueError("lesson requires principles and quiz questions")


class GeminiTradingTeacher:
    """Gemini-backed curriculum teacher for bounded trading education.

    It teaches concepts and critiques reasoning; it is not a market oracle and is
    never given authority to place orders, modify the mandate, or promote skills.
    """

    LESSON_SCHEMA = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "summary": {"type": "string"},
            "principles": {"type": "array", "items": {"type": "string"}},
            "examples": {"type": "array", "items": {"type": "string"}},
            "safety_notes": {"type": "array", "items": {"type": "string"}},
            "quiz": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "choices": {"type": "array", "items": {"type": "string"}},
                        "correct_index": {"type": "integer"},
                        "explanation": {"type": "string"},
                    },
                    "required": ["question", "choices", "correct_index", "explanation"],
                },
            },
        },
        "required": ["title", "summary", "principles", "examples", "safety_notes", "quiz"],
    }

    SYSTEM = """You are the senior trading-systems TEACHER for NEXA, a local autonomous AI platform.
Teach robust engineering and statistical reasoning, not promises of profit. Never claim certainty, never
provide a live trade signal, and never tell the student to bypass risk controls. Use hypothetical examples.
Focus on data integrity, realistic execution, out-of-sample validation, drawdown control, and explicit
no-trade states. Return only the requested structured JSON."""

    def __init__(self, bridge: GeminiBridge | None = None, *, quiz_questions: int = 5) -> None:
        if quiz_questions < 3 or quiz_questions > 10:
            raise ValueError("quiz_questions must be between 3 and 10")
        self.bridge = bridge or GeminiBridge()
        self.quiz_questions = quiz_questions

    def available(self) -> bool:
        return self.bridge.available()

    def teach(
        self,
        module: CurriculumModule,
        *,
        previous_score: float | None = None,
        weakness_note: str | None = None,
    ) -> TradingLesson:
        adaptation = "First attempt."
        if previous_score is not None:
            adaptation = f"Previous deterministic quiz score: {previous_score:.2f}."
        if weakness_note:
            adaptation += f" Weakness to address: {weakness_note.strip()}"

        prompt = f"""Create one compact but technically rigorous lesson for this curriculum module.

Module id: {module.module_id}
Title: {module.title}
Objective: {module.objective}
Topics: {', '.join(module.topics)}
Mandatory safety focus: {module.safety_focus}
Mastery threshold: {module.minimum_score:.2f}
Adaptation context: {adaptation}

Requirements:
- Explain mechanisms, assumptions, and failure modes, not slogans.
- Give 2-4 hypothetical examples using invented prices/data only.
- Include at least 3 explicit safety notes.
- Create exactly {self.quiz_questions} multiple-choice questions.
- Each question must have 4 plausible choices and exactly one correct choice.
- correct_index is zero-based.
- The quiz must test reasoning, not wording memorization.
- Do not include current market recommendations or claims of guaranteed returns.
""".strip()

        payload = self.bridge.generate_json(
            prompt,
            self.LESSON_SCHEMA,
            system_instruction=self.SYSTEM,
        )
        quiz = tuple(
            QuizQuestion(
                question=str(item["question"]).strip(),
                choices=tuple(str(choice).strip() for choice in item["choices"]),
                correct_index=int(item["correct_index"]),
                explanation=str(item["explanation"]).strip(),
            )
            for item in payload["quiz"]
        )
        if len(quiz) != self.quiz_questions:
            raise ValueError(
                f"teacher returned {len(quiz)} quiz questions; expected {self.quiz_questions}"
            )
        return TradingLesson(
            module_id=module.module_id,
            title=str(payload["title"]).strip(),
            summary=str(payload["summary"]).strip(),
            principles=tuple(str(item).strip() for item in payload["principles"] if str(item).strip()),
            examples=tuple(str(item).strip() for item in payload["examples"] if str(item).strip()),
            safety_notes=tuple(str(item).strip() for item in payload["safety_notes"] if str(item).strip()),
            quiz=quiz,
            provider=f"gemini:{self.bridge.model}",
        )
