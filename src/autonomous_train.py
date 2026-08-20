from __future__ import annotations

import argparse
import os
from pathlib import Path

from bridges import GeminiBridge, OllamaBridge
from training import (
    AutonomousLearningSupervisor,
    AutonomousTrainingEngine,
    CandidateStore,
    GeminiTradingTeacher,
    ImprovementBacklog,
    SkillForge,
    TradingCurriculum,
    TrainingStore,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "training.db"
DEFAULT_CANDIDATES = PROJECT_ROOT / "data" / "generated_skills"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run NEXA's bounded autonomous teacher-student training supervisor"
    )
    parser.add_argument("--status", action="store_true", help="show curriculum progress and exit")
    parser.add_argument("--attempts", type=int, default=3, help="student attempts per module round")
    parser.add_argument("--module-rounds", type=int, default=30, help="maximum autonomous module rounds")
    parser.add_argument("--rounds-per-module", type=int, default=4, help="maximum failed rounds for one module")
    parser.add_argument("--teacher-calls", type=int, default=100, help="total Gemini lesson-call budget")
    parser.add_argument("--student-calls", type=int, default=150, help="total local student-call budget")
    parser.add_argument("--forge-items", type=int, default=5, help="maximum queued skill gaps to forge after curriculum")
    parser.add_argument("--no-forge", action="store_true", help="skip queued skill forging")
    parser.add_argument("--queue-skill", default=None, help="queue a capability gap before training")
    parser.add_argument("--gap-risk", choices=("read", "mutate", "remote", "destructive"), default="read")
    parser.add_argument("--gap-context", default="")
    parser.add_argument("--queue-only", action="store_true", help="queue the requested skill and exit")
    parser.add_argument("--db", default=os.getenv("NEXA_TRAINING_DB", str(DEFAULT_DB)))
    parser.add_argument("--candidate-dir", default=os.getenv("NEXA_CANDIDATE_DIR", str(DEFAULT_CANDIDATES)))
    parser.add_argument("--teacher-model", default=os.getenv("GEMINI_MODEL") or None)
    parser.add_argument("--student-model", default=os.getenv("OLLAMA_MODEL", "qwen3:1.7b"))
    return parser


def print_status(store: TrainingStore, curriculum: TradingCurriculum, backlog: ImprovementBacklog) -> None:
    print("NEXA Autonomous Trading Learning")
    print("=" * 78)
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
            state = "LEARNING"
            detail = f"best={progress['best_score']:.2f}, attempts={progress['attempts']}"
        print(f"[{state:8}] {module.module_id:30} {detail}")
    print("-" * 78)
    print(f"Mastered: {mastered}/{len(curriculum.modules)}")
    print(f"Queued capability gaps: {len(backlog.pending(100))}")


def main() -> int:
    args = build_parser().parse_args()
    if min(args.attempts, args.module_rounds, args.rounds_per_module, args.teacher_calls, args.student_calls) <= 0:
        raise SystemExit("training budgets must be positive")
    if args.forge_items < 0:
        raise SystemExit("forge-items cannot be negative")

    db_path = Path(args.db).expanduser().resolve()
    candidate_dir = Path(args.candidate_dir).expanduser().resolve()
    store = TrainingStore(db_path)
    backlog = ImprovementBacklog(db_path)
    curriculum = TradingCurriculum()

    if args.queue_skill:
        gap_id = backlog.enqueue(
            args.queue_skill,
            risk_tier=args.gap_risk,
            context=args.gap_context,
        )
        print(f"Queued capability gap: {gap_id}")
        if args.queue_only:
            return 0
    elif args.queue_only:
        raise SystemExit("--queue-only requires --queue-skill")

    if args.status:
        print_status(store, curriculum, backlog)
        return 0

    if not os.getenv("GEMINI_API_KEY", "").strip():
        print("Autonomous training stopped: GEMINI_API_KEY is not available in this process.")
        return 2

    teacher_bridge = GeminiBridge(model=args.teacher_model)
    teacher = GeminiTradingTeacher(teacher_bridge)
    student = OllamaBridge(model=args.student_model)

    def engine_builder(selected: TradingCurriculum, teacher_budget: int, student_budget: int):
        return AutonomousTrainingEngine(
            curriculum=selected,
            teacher=teacher,
            student=student,
            store=store,
            max_attempts_per_module=args.attempts,
            max_teacher_calls=max(1, teacher_budget),
            max_student_calls=max(1, student_budget),
        )

    forge = None if args.no_forge else SkillForge(bridge=teacher_bridge)
    candidate_store = None if args.no_forge else CandidateStore(candidate_dir)
    supervisor = AutonomousLearningSupervisor(
        curriculum=curriculum,
        store=store,
        engine_builder=engine_builder,
        backlog=backlog,
        skill_forge=forge,
        candidate_store=candidate_store,
        max_module_rounds=args.module_rounds,
        max_rounds_per_module=args.rounds_per_module,
        max_teacher_calls=args.teacher_calls,
        max_student_calls=args.student_calls,
        max_forge_items=0 if args.no_forge else args.forge_items,
    )

    print("Starting NEXA bounded autonomous learning...")
    print(f"Training DB: {db_path}")
    print(f"Candidate staging: {candidate_dir}")
    print(f"Teacher model: {teacher_bridge.model}")
    print(f"Student model: {student.model}")
    print(
        "Budgets: "
        f"module_rounds={args.module_rounds}, rounds/module={args.rounds_per_module}, "
        f"teacher_calls={args.teacher_calls}, student_calls={args.student_calls}, "
        f"forge_items={0 if args.no_forge else args.forge_items}"
    )

    summary = supervisor.run()
    print("\nAutonomous learning summary")
    print("=" * 78)
    print(f"Curriculum complete: {summary.curriculum_complete}")
    print(f"Module rounds: {summary.module_rounds}")
    print(f"Teacher calls: {summary.teacher_calls}")
    print(f"Student calls: {summary.student_calls}")
    print(f"Skill gaps forged: {summary.forged}")
    print(f"Candidates staged: {summary.staged}")
    print(f"Stopped: {summary.stopped_reason}")
    print("Live trading remains unchanged; training cannot arm a broker or bypass RiskEngine.")
    return 0 if summary.curriculum_complete else 1


if __name__ == "__main__":
    raise SystemExit(main())
