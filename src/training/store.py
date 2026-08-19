from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .trading_teacher import QuizQuestion, TradingLesson


class TrainingStore:
    """Persistent local curriculum state for teacher-student training."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at_utc TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    provider TEXT NOT NULL,
                    lesson_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at_utc TEXT NOT NULL,
                    module_id TEXT NOT NULL,
                    lesson_id INTEGER NOT NULL,
                    score REAL NOT NULL,
                    answers_json TEXT NOT NULL,
                    feedback_json TEXT NOT NULL,
                    FOREIGN KEY(lesson_id) REFERENCES training_lessons(id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS training_progress (
                    module_id TEXT PRIMARY KEY,
                    best_score REAL NOT NULL,
                    attempts INTEGER NOT NULL,
                    mastered INTEGER NOT NULL,
                    updated_at_utc TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_training_attempt_module ON training_attempts(module_id, id)"
            )

    def save_lesson(self, lesson: TradingLesson) -> int:
        payload = json.dumps(asdict(lesson), sort_keys=True, separators=(",", ":"))
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO training_lessons(created_at_utc, module_id, provider, lesson_json)
                VALUES (?, ?, ?, ?)
                """,
                (now, lesson.module_id, lesson.provider, payload),
            )
            return int(cursor.lastrowid)

    def record_attempt(
        self,
        *,
        module_id: str,
        lesson_id: int,
        score: float,
        answers: tuple[int, ...],
        feedback: tuple[str, ...],
        mastered: bool,
    ) -> int:
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be between 0 and 1")
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO training_attempts(
                    created_at_utc, module_id, lesson_id, score, answers_json, feedback_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    module_id,
                    lesson_id,
                    score,
                    json.dumps(list(answers), separators=(",", ":")),
                    json.dumps(list(feedback), separators=(",", ":")),
                ),
            )
            current = connection.execute(
                "SELECT best_score, attempts, mastered FROM training_progress WHERE module_id = ?",
                (module_id,),
            ).fetchone()
            best = max(score, float(current["best_score"])) if current is not None else score
            attempts = int(current["attempts"]) + 1 if current is not None else 1
            mastered_value = bool(current["mastered"]) or mastered if current is not None else mastered
            connection.execute(
                """
                INSERT INTO training_progress(module_id, best_score, attempts, mastered, updated_at_utc)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(module_id) DO UPDATE SET
                    best_score=excluded.best_score,
                    attempts=excluded.attempts,
                    mastered=excluded.mastered,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (module_id, best, attempts, 1 if mastered_value else 0, now),
            )
            return int(cursor.lastrowid)

    def latest_score(self, module_id: str) -> float | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT score FROM training_attempts WHERE module_id = ? ORDER BY id DESC LIMIT 1",
                (module_id,),
            ).fetchone()
        return None if row is None else float(row["score"])

    def progress(self, module_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM training_progress WHERE module_id = ?",
                (module_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "module_id": row["module_id"],
            "best_score": float(row["best_score"]),
            "attempts": int(row["attempts"]),
            "mastered": bool(row["mastered"]),
            "updated_at_utc": row["updated_at_utc"],
        }

    def mastered_modules(self) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT module_id FROM training_progress WHERE mastered = 1 ORDER BY module_id"
            ).fetchall()
        return tuple(str(row["module_id"]) for row in rows)

    def latest_lesson(self, module_id: str) -> TradingLesson | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT lesson_json FROM training_lessons WHERE module_id = ? ORDER BY id DESC LIMIT 1",
                (module_id,),
            ).fetchone()
        if row is None:
            return None
        payload = json.loads(row["lesson_json"])
        quiz = tuple(
            QuizQuestion(
                question=item["question"],
                choices=tuple(item["choices"]),
                correct_index=int(item["correct_index"]),
                explanation=item["explanation"],
            )
            for item in payload["quiz"]
        )
        return TradingLesson(
            module_id=payload["module_id"],
            title=payload["title"],
            summary=payload["summary"],
            principles=tuple(payload["principles"]),
            examples=tuple(payload["examples"]),
            safety_notes=tuple(payload["safety_notes"]),
            quiz=quiz,
            provider=payload["provider"],
        )
