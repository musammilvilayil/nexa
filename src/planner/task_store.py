from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from planner.contracts import TaskPlan, PlanStep, TaskRecord, PlanStatus, StepStatus


class TaskStore:
    """Thread-safe SQLite storage for task history, state, and execution records."""

    def __init__(self, db_path: Path | str) -> None:
        self.is_memory = str(db_path) == ":memory:"
        if self.is_memory:
            self.db_path = ":memory:"
            self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._mem_conn.row_factory = sqlite3.Row
        else:
            self.db_path = Path(db_path).expanduser().resolve()
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._mem_conn = None
        self._lock = threading.Lock()
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self.is_memory:
            return self._mem_conn
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    goal TEXT NOT NULL,
                    state TEXT NOT NULL,
                    current_step INTEGER NOT NULL DEFAULT 0,
                    risk TEXT NOT NULL DEFAULT 'mutate',
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    attempt_count INTEGER NOT NULL DEFAULT 1,
                    verification_result TEXT NOT NULL DEFAULT '',
                    failure_reason TEXT,
                    recovery_count INTEGER NOT NULL DEFAULT 0,
                    plan_json TEXT NOT NULL
                )
            """)
            conn.commit()

    def save_task(self, record: TaskRecord) -> None:
        steps_data = [
            {
                "step_id": s.step_id,
                "description": s.description,
                "skill_name": s.skill_name,
                "operation": s.operation,
                "params": s.params,
                "status": s.status.value,
                "retry_count": s.retry_count,
                "error": s.error,
            }
            for s in record.plan.steps
        ]
        plan_data = {
            "plan_id": record.plan.plan_id,
            "description": record.plan.description,
            "status": record.plan.status.value,
            "steps": steps_data,
        }
        with self._lock, self._get_connection() as conn:
            conn.execute("""
                INSERT INTO tasks (
                    task_id, goal, state, current_step, risk, started_at, updated_at,
                    attempt_count, verification_result, failure_reason, recovery_count, plan_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    state=excluded.state,
                    current_step=excluded.current_step,
                    updated_at=excluded.updated_at,
                    attempt_count=excluded.attempt_count,
                    verification_result=excluded.verification_result,
                    failure_reason=excluded.failure_reason,
                    recovery_count=excluded.recovery_count,
                    plan_json=excluded.plan_json
            """, (
                record.task_id,
                record.goal,
                record.state,
                record.current_step,
                record.risk,
                record.started_at,
                record.updated_at,
                record.attempt_count,
                record.verification_result,
                record.failure_reason,
                record.recovery_count,
                json.dumps(plan_data),
            ))
            conn.commit()

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def list_tasks(self, limit: int = 20) -> list[TaskRecord]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM tasks ORDER BY updated_at DESC LIMIT ?", (limit,))
            return [self._row_to_record(row) for row in cur.fetchall()]

    def list_active_tasks(self) -> list[TaskRecord]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM tasks WHERE state IN ('in_progress', 'running', 'pending') ORDER BY updated_at DESC"
            )
            return [self._row_to_record(row) for row in cur.fetchall()]

    def cancel_task(self, task_id: str) -> bool:
        record = self.get_task(task_id)
        if not record:
            return False
        record.state = "cancelled"
        record.plan.status = PlanStatus.CANCELLED
        self.save_task(record)
        return True

    def _row_to_record(self, row: sqlite3.Row) -> TaskRecord:
        plan_data = json.loads(row["plan_json"])
        steps = [
            PlanStep(
                step_id=s["step_id"],
                description=s["description"],
                skill_name=s["skill_name"],
                operation=s["operation"],
                params=s.get("params", {}),
                status=StepStatus(s.get("status", "pending")),
                retry_count=s.get("retry_count", 0),
                error=s.get("error"),
            )
            for s in plan_data.get("steps", [])
        ]
        plan = TaskPlan(
            plan_id=plan_data["plan_id"],
            description=plan_data["description"],
            steps=steps,
            status=PlanStatus(plan_data.get("status", "pending")),
        )
        return TaskRecord(
            task_id=row["task_id"],
            goal=row["goal"],
            plan=plan,
            current_step=row["current_step"],
            state=row["state"],
            risk=row["risk"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
            attempt_count=row["attempt_count"],
            verification_result=row["verification_result"],
            failure_reason=row["failure_reason"],
            recovery_count=row["recovery_count"],
        )
