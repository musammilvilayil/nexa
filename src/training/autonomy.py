from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from sqlite_utils import connect_sqlite

from .candidate_store import CandidateStore
from .curriculum import CurriculumModule, TradingCurriculum
from .engine import AutonomousTrainingEngine
from .skill_forge import SkillForge
from .store import TrainingStore


_ALLOWED_GAP_RISKS = {"read", "mutate", "remote", "destructive"}


@dataclass(frozen=True)
class CapabilityGap:
    gap_id: str
    capability: str
    risk_tier: str
    context: str
    status: str


class ImprovementBacklog:
    """Persistent queue for deterministic capability gaps discovered by NEXA."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_gaps (
                    gap_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    risk_tier TEXT NOT NULL,
                    context TEXT NOT NULL,
                    status TEXT NOT NULL,
                    staged_path TEXT,
                    error TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path)

    def enqueue(self, capability: str, *, risk_tier: str = "read", context: str = "") -> str:
        capability = capability.strip()
        risk = risk_tier.strip().lower()
        if not capability:
            raise ValueError("capability cannot be empty")
        if risk not in _ALLOWED_GAP_RISKS:
            raise ValueError("unsupported capability risk tier")
        gap_id = uuid4().hex[:12]
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO capability_gaps(
                    gap_id, created_at_utc, updated_at_utc, capability,
                    risk_tier, context, status
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending')
                """,
                (gap_id, now, now, capability, risk, context.strip()),
            )
        return gap_id

    def pending(self, limit: int = 10) -> tuple[CapabilityGap, ...]:
        if limit <= 0 or limit > 100:
            raise ValueError("limit must be between 1 and 100")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT gap_id, capability, risk_tier, context, status
                FROM capability_gaps
                WHERE status = 'pending'
                ORDER BY created_at_utc, gap_id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(
            CapabilityGap(
                gap_id=row["gap_id"],
                capability=row["capability"],
                risk_tier=row["risk_tier"],
                context=row["context"],
                status=row["status"],
            )
            for row in rows
        )

    def mark_staged(self, gap_id: str, path: Path) -> None:
        self._mark(gap_id, "staged", staged_path=str(path), error=None)

    def mark_failed(self, gap_id: str, error: str) -> None:
        self._mark(gap_id, "failed", staged_path=None, error=error[:4000])

    def _mark(
        self,
        gap_id: str,
        status: str,
        *,
        staged_path: str | None,
        error: str | None,
    ) -> None:
        if status not in {"staged", "failed"}:
            raise ValueError("invalid backlog status")
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE capability_gaps
                SET status = ?, updated_at_utc = ?, staged_path = ?, error = ?
                WHERE gap_id = ? AND status = 'pending'
                """,
                (
                    status,
                    datetime.now(timezone.utc).isoformat(),
                    staged_path,
                    error,
                    gap_id,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("capability gap is missing or no longer pending")


@dataclass(frozen=True)
class LearningWeakness:
    module_id: str
    title: str
    attempts: int
    best_score: float


class DeficiencyDetector:
    """Deterministically chooses the next unmastered curriculum weakness."""

    def next_weakness(
        self,
        curriculum: TradingCurriculum,
        store: TrainingStore,
    ) -> LearningWeakness | None:
        for module in curriculum.modules:
            progress = store.progress(module.module_id)
            if progress is not None and progress["mastered"]:
                continue
            return LearningWeakness(
                module_id=module.module_id,
                title=module.title,
                attempts=0 if progress is None else int(progress["attempts"]),
                best_score=0.0 if progress is None else float(progress["best_score"]),
            )
        return None


@dataclass(frozen=True)
class AutonomousLearningSummary:
    curriculum_complete: bool
    module_rounds: int
    teacher_calls: int
    student_calls: int
    forged: int
    staged: int
    stopped_reason: str


EngineBuilder = Callable[[TradingCurriculum, int, int], AutonomousTrainingEngine]


class AutonomousLearningSupervisor:
    """Finite self-training + skill-forge coordinator.

    Curriculum learning can run without human intervention until a deterministic
    budget or mastery boundary is reached. Skill generation only processes queued
    capability gaps, and successful candidates are staged outside the live source
    tree. No generated code is auto-imported, no core file is rewritten, and no
    live-trading capability can be enabled by this supervisor.
    """

    def __init__(
        self,
        *,
        curriculum: TradingCurriculum,
        store: TrainingStore,
        engine_builder: EngineBuilder,
        backlog: ImprovementBacklog | None = None,
        skill_forge: SkillForge | None = None,
        candidate_store: CandidateStore | None = None,
        max_module_rounds: int = 30,
        max_rounds_per_module: int = 4,
        max_teacher_calls: int = 100,
        max_student_calls: int = 150,
        max_forge_items: int = 5,
        deficiency_detector: DeficiencyDetector | None = None,
    ) -> None:
        if min(max_module_rounds, max_rounds_per_module, max_teacher_calls, max_student_calls) <= 0:
            raise ValueError("autonomous learning budgets must be positive")
        if max_forge_items < 0:
            raise ValueError("max_forge_items cannot be negative")
        self.curriculum = curriculum
        self.store = store
        self.engine_builder = engine_builder
        self.backlog = backlog
        self.skill_forge = skill_forge
        self.candidate_store = candidate_store
        self.max_module_rounds = int(max_module_rounds)
        self.max_rounds_per_module = int(max_rounds_per_module)
        self.max_teacher_calls = int(max_teacher_calls)
        self.max_student_calls = int(max_student_calls)
        self.max_forge_items = int(max_forge_items)
        self.deficiency_detector = deficiency_detector or DeficiencyDetector()

    def run(self) -> AutonomousLearningSummary:
        teacher_calls = 0
        student_calls = 0
        module_rounds = 0
        failures_by_module: dict[str, int] = {}

        while module_rounds < self.max_module_rounds:
            weakness = self.deficiency_detector.next_weakness(self.curriculum, self.store)
            if weakness is None:
                break
            if teacher_calls >= self.max_teacher_calls:
                return self._summary(False, module_rounds, teacher_calls, student_calls, 0, 0, "teacher call budget reached")
            if student_calls >= self.max_student_calls:
                return self._summary(False, module_rounds, teacher_calls, student_calls, 0, 0, "student call budget reached")

            module = self._module(weakness.module_id)
            one_module = TradingCurriculum((module,))
            engine = self.engine_builder(
                one_module,
                self.max_teacher_calls - teacher_calls,
                self.max_student_calls - student_calls,
            )
            result = engine.run()
            module_rounds += 1
            teacher_calls += result.teacher_calls
            student_calls += result.student_calls

            progress = self.store.progress(module.module_id)
            mastered = bool(progress and progress["mastered"])
            if mastered:
                failures_by_module.pop(module.module_id, None)
                continue

            failures = failures_by_module.get(module.module_id, 0) + 1
            failures_by_module[module.module_id] = failures
            if failures >= self.max_rounds_per_module:
                return self._summary(
                    False,
                    module_rounds,
                    teacher_calls,
                    student_calls,
                    0,
                    0,
                    f"module mastery retry limit reached: {module.module_id}",
                )

        curriculum_complete = self.deficiency_detector.next_weakness(self.curriculum, self.store) is None
        if not curriculum_complete:
            return self._summary(
                False,
                module_rounds,
                teacher_calls,
                student_calls,
                0,
                0,
                "module round budget reached",
            )

        forged, staged = self._process_backlog()
        return self._summary(
            True,
            module_rounds,
            teacher_calls,
            student_calls,
            forged,
            staged,
            "curriculum complete; queued skill candidates processed",
        )

    def _process_backlog(self) -> tuple[int, int]:
        if (
            self.max_forge_items == 0
            or self.backlog is None
            or self.skill_forge is None
            or self.candidate_store is None
        ):
            return 0, 0

        forged = 0
        staged = 0
        for gap in self.backlog.pending(self.max_forge_items):
            forged += 1
            try:
                result = self.skill_forge.forge(
                    gap.capability,
                    risk_tier=gap.risk_tier,
                    context=gap.context or None,
                )
                if not result.passed or result.candidate is None:
                    self.backlog.mark_failed(gap.gap_id, result.reason)
                    continue
                path = self.candidate_store.stage(result.candidate)
                self.backlog.mark_staged(gap.gap_id, path)
                staged += 1
            except Exception as exc:
                self.backlog.mark_failed(gap.gap_id, str(exc))
        return forged, staged

    def _module(self, module_id: str) -> CurriculumModule:
        return self.curriculum.get(module_id)

    @staticmethod
    def _summary(
        complete: bool,
        module_rounds: int,
        teacher_calls: int,
        student_calls: int,
        forged: int,
        staged: int,
        reason: str,
    ) -> AutonomousLearningSummary:
        return AutonomousLearningSummary(
            curriculum_complete=complete,
            module_rounds=module_rounds,
            teacher_calls=teacher_calls,
            student_calls=student_calls,
            forged=forged,
            staged=staged,
            stopped_reason=reason,
        )
