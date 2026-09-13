from __future__ import annotations

import argparse
import os
from pathlib import Path

from bridges import GeminiBridge, OllamaBridge
from training import AutonomousTrainingEngine, GeminiTradingTeacher, TradingCurriculum, TrainingStore


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "training.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run NEXA's bounded autonomous trading curriculum")
    parser.add_argument("--status", action="store_true", help="show curriculum progress without calling models")
    parser.add_argument("--max-modules", type=int, default=None, help="train at most N modules this run")
    parser.add_argument("--attempts", type=int, default=3, help="maximum attempts per module")
    parser.add_argument("--teacher-calls", type=int, default=40, help="teacher API call budget")
    parser.add_argument("--student-calls", type=int, default=60, help="local student call budget")
    parser.add_argument("--db", default=os.getenv("NEXA_TRAINING_DB", str(DEFAULT_DB)))
    parser.add_argument("--teacher-model", default=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"))
    parser.add_argument("--student-model", default=os.getenv("NEXA_OLLAMA_MODEL", "qwen3:1.7b"))
    return parser


def print_status(store: TrainingStore, curriculum: TradingCurriculum) -> None:
    print("NEXA Trading Curriculum")
    print("=" * 72)
    mastered = 0
    for module in curriculum.modules:
        progress = store.progress(module.module_id)
        if progress is None:
            state = "PENDING"
            detail = "no attempts"
        elif progress["mastered"]:
            mastered += 1
            state = "MASTERED"
            detail = f"best={progress['best_score']:.2f}, attempts={progress['attempts']}"
        else:
            state = "IN PROGRESS"
            detail = f"best={progress['best_score']:.2f}, attempts={progress['attempts']}"
        print(f"[{state:11}] {module.module_id:28} {detail}")
    print("-" * 72)
    print(f"Mastered: {mastered}/{len(curriculum.modules)}")


def main() -> int:
    args = build_parser().parse_args()
    db_path = Path(args.db).expanduser().resolve()
    store = TrainingStore(db_path)
    curriculum = TradingCurriculum()

    if args.status:
        print_status(store, curriculum)
        return 0

    if not os.getenv("GEMINI_API_KEY", "").strip():
        print("Training stopped: GEMINI_API_KEY is not available in this process.")
        return 2

    teacher_bridge = GeminiBridge(model=args.teacher_model)
    teacher = GeminiTradingTeacher(teacher_bridge)
    student = OllamaBridge(model=args.student_model)
    engine = AutonomousTrainingEngine(
        curriculum=curriculum,
        teacher=teacher,
        student=student,
        store=store,
        max_attempts_per_module=args.attempts,
        max_teacher_calls=args.teacher_calls,
        max_student_calls=args.student_calls,
    )

    print("Starting bounded NEXA autonomous trading training...")
    print(f"Training DB: {db_path}")
    print(f"Teacher: {args.teacher_model}")
    print(f"Student: {args.student_model}")
    print(
        f"Budgets: attempts/module={args.attempts}, teacher_calls={args.teacher_calls}, "
        f"student_calls={args.student_calls}"
    )

    summary = engine.run(max_modules=args.max_modules)
    print("\nTraining run summary")
    print("=" * 72)
    for item in summary.modules:
        state = "MASTERED" if item.mastered else "FAILED"
        print(
            f"[{state:8}] {item.module_id:28} best={item.best_score:.2f} "
            f"attempts={item.attempts} - {item.reason}"
        )
    print("-" * 72)
    print(f"Teacher calls: {summary.teacher_calls}")
    print(f"Student calls: {summary.student_calls}")
    print(f"Stopped: {summary.stopped_reason}")
    print(f"Complete: {summary.completed}")

    # Training completion deliberately does not arm or enable live trading.
    return 0 if summary.completed else 1


if __name__ == "__main__":
    raise SystemExit(main())
