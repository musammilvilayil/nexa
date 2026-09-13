from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from core.contracts import RiskTier
from core.security import SecurityGate
from extensions.contracts import ExtensionStatus, LifecycleExtension


class ScheduleType(str, Enum):
    ONCE = "once"
    INTERVAL = "interval"
    DAILY = "daily"
    WEEKLY = "weekly"
    CRON = "cron"


@dataclass
class ScheduledJob:
    job_id: str
    name: str
    schedule_type: ScheduleType
    expression: str
    goal: str
    params: dict[str, Any] = field(default_factory=dict)
    next_run_at: float = 0.0
    last_run_at: float | None = None
    run_count: int = 0
    enabled: bool = True
    created_at: float = field(default_factory=time.time)


class SchedulerExtension(LifecycleExtension):
    """Persistent task scheduler executing one-off, interval, daily, or cron tasks across restarts."""

    def __init__(
        self,
        db_path: str | Path = ":memory:",
        security_gate: SecurityGate | None = None,
        executor_callback: Callable[[ScheduledJob], Any] | None = None,
    ) -> None:
        self._db_path = str(db_path)
        self.security_gate = security_gate
        self.executor_callback = executor_callback
        self._mem_conn: sqlite3.Connection | None = None
        self._status = ExtensionStatus.DISCOVERED
        self._lock = threading.Lock()
        self._worker_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._jobs: dict[str, ScheduledJob] = {}

        self._init_db()
        self._load_jobs()

    def _get_conn(self) -> sqlite3.Connection:
        if self._db_path == ":memory:":
            if self._mem_conn is None:
                self._mem_conn = sqlite3.connect(":memory:", check_same_thread=False)
            return self._mem_conn
        return sqlite3.connect(self._db_path)

    def _init_db(self) -> None:
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = self._get_conn()
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                job_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                schedule_type TEXT NOT NULL,
                expression TEXT NOT NULL,
                goal TEXT NOT NULL,
                params_json TEXT NOT NULL,
                next_run_at REAL NOT NULL,
                last_run_at REAL,
                run_count INTEGER NOT NULL,
                enabled INTEGER NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        conn.commit()
        if self._db_path != ":memory:":
            conn.close()

    def _load_jobs(self) -> None:
        conn = self._get_conn()
        try:
            cursor = conn.execute("SELECT * FROM scheduled_jobs")
            for row in cursor.fetchall():
                job = ScheduledJob(
                    job_id=row[0],
                    name=row[1],
                    schedule_type=ScheduleType(row[2]),
                    expression=row[3],
                    goal=row[4],
                    params=json.loads(row[5]) if row[5] else {},
                    next_run_at=row[6],
                    last_run_at=row[7],
                    run_count=row[8],
                    enabled=bool(row[9]),
                    created_at=row[10],
                )
                self._jobs[job.job_id] = job
        finally:
            if self._db_path != ":memory:":
                conn.close()

    def _persist_job(self, job: ScheduledJob) -> None:
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO scheduled_jobs (job_id, name, schedule_type, expression, goal, params_json, next_run_at, last_run_at, run_count, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(job_id) DO UPDATE SET
                    next_run_at=excluded.next_run_at,
                    last_run_at=excluded.last_run_at,
                    run_count=excluded.run_count,
                    enabled=excluded.enabled
                """,
                (
                    job.job_id,
                    job.name,
                    job.schedule_type.value,
                    job.expression,
                    job.goal,
                    json.dumps(job.params),
                    job.next_run_at,
                    job.last_run_at,
                    job.run_count,
                    1 if job.enabled else 0,
                    job.created_at,
                ),
            )
            conn.commit()
        finally:
            if self._db_path != ":memory:":
                conn.close()

    # ── Lifecycle Methods ─────────────────────────────────────────────
    def initialize(self) -> bool:
        with self._lock:
            self._status = ExtensionStatus.ACTIVE
            self._stop_event.clear()
            return True

    def shutdown(self) -> bool:
        with self._lock:
            self._stop_event.set()
            self._status = ExtensionStatus.STOPPED
            if self._mem_conn:
                self._mem_conn.close()
                self._mem_conn = None
            return True

    def health_check(self) -> dict[str, Any]:
        with self._lock:
            active_jobs = sum(1 for j in self._jobs.values() if j.enabled)
            return {
                "healthy": self._status == ExtensionStatus.ACTIVE,
                "status": self._status.value,
                "total_jobs": len(self._jobs),
                "active_jobs": active_jobs,
            }

    def is_available(self) -> bool:
        return self._status in (ExtensionStatus.ACTIVE, ExtensionStatus.INITIALIZED)

    # ── Scheduling Methods ────────────────────────────────────────────
    def schedule_once(
        self,
        name: str,
        run_at: float,
        goal: str,
        params: dict[str, Any] | None = None,
    ) -> ScheduledJob:
        with self._lock:
            job_id = f"job_{uuid4().hex[:8]}"
            job = ScheduledJob(
                job_id=job_id,
                name=name,
                schedule_type=ScheduleType.ONCE,
                expression=str(run_at),
                goal=goal,
                params=params or {},
                next_run_at=run_at,
                enabled=True,
            )
            self._jobs[job_id] = job
            self._persist_job(job)
            return job

    def schedule_interval(
        self,
        name: str,
        interval_seconds: float,
        goal: str,
        params: dict[str, Any] | None = None,
    ) -> ScheduledJob:
        with self._lock:
            job_id = f"job_{uuid4().hex[:8]}"
            next_run = time.time() + max(0.1, interval_seconds)
            job = ScheduledJob(
                job_id=job_id,
                name=name,
                schedule_type=ScheduleType.INTERVAL,
                expression=str(interval_seconds),
                goal=goal,
                params=params or {},
                next_run_at=next_run,
                enabled=True,
            )
            self._jobs[job_id] = job
            self._persist_job(job)
            return job

    def schedule_daily(
        self,
        name: str,
        time_str: str,  # "HH:MM"
        goal: str,
        params: dict[str, Any] | None = None,
    ) -> ScheduledJob:
        with self._lock:
            job_id = f"job_{uuid4().hex[:8]}"
            # Compute next run timestamp today or tomorrow
            now = datetime.now()
            parts = [int(p) for p in time_str.split(":")[:2]]
            target = now.replace(hour=parts[0], minute=parts[1], second=0, microsecond=0)
            if target <= now:
                target = target.replace(day=target.day + 1)
            next_run = target.timestamp()

            job = ScheduledJob(
                job_id=job_id,
                name=name,
                schedule_type=ScheduleType.DAILY,
                expression=time_str,
                goal=goal,
                params=params or {},
                next_run_at=next_run,
                enabled=True,
            )
            self._jobs[job_id] = job
            self._persist_job(job)
            return job

    def schedule_cron(
        self,
        name: str,
        cron_expr: str,
        goal: str,
        params: dict[str, Any] | None = None,
    ) -> ScheduledJob:
        with self._lock:
            job_id = f"job_{uuid4().hex[:8]}"
            # Default to 1 hour from now for arbitrary cron expression if croniter not present
            next_run = time.time() + 3600.0
            job = ScheduledJob(
                job_id=job_id,
                name=name,
                schedule_type=ScheduleType.CRON,
                expression=cron_expr,
                goal=goal,
                params=params or {},
                next_run_at=next_run,
                enabled=True,
            )
            self._jobs[job_id] = job
            self._persist_job(job)
            return job

    def list_jobs(self, enabled_only: bool = False) -> list[ScheduledJob]:
        with self._lock:
            jobs = list(self._jobs.values())
            if enabled_only:
                jobs = [j for j in jobs if j.enabled]
            return sorted(jobs, key=lambda j: j.next_run_at)

    def get_job(self, job_id: str) -> ScheduledJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def pause_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job.enabled = False
            self._persist_job(job)
            return True

    def resume_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            job.enabled = True
            if job.next_run_at < time.time():
                job.next_run_at = time.time() + 1.0
            self._persist_job(job)
            return True

    def cancel_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.pop(job_id, None)
            if not job:
                return False
            conn = self._get_conn()
            try:
                conn.execute("DELETE FROM scheduled_jobs WHERE job_id = ?", (job_id,))
                conn.commit()
            finally:
                if self._db_path != ":memory:":
                    conn.close()
            return True

    def trigger_job(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False

        # Security gate check if available
        if self.security_gate:
            decision = self.security_gate.evaluate(
                skill_name="scheduler",
                operation="trigger",
                params={"job_id": job.job_id, "goal": job.goal},
                risk=RiskTier.MUTATE,
            )
            if decision.outcome.value == "deny":
                return False

        # Execute
        try:
            if self.executor_callback:
                self.executor_callback(job)
        except Exception:
            pass

        with self._lock:
            job.last_run_at = time.time()
            job.run_count += 1
            if job.schedule_type == ScheduleType.ONCE:
                job.enabled = False
            elif job.schedule_type == ScheduleType.INTERVAL:
                try:
                    ival = float(job.expression)
                except ValueError:
                    ival = 60.0
                job.next_run_at = time.time() + ival
            elif job.schedule_type == ScheduleType.DAILY:
                job.next_run_at = time.time() + 86400.0
            self._persist_job(job)

        return True

    def tick(self) -> list[str]:
        """Checks due jobs and triggers them. Returns list of triggered job_ids."""
        now = time.time()
        due_ids: list[str] = []

        with self._lock:
            for job in self._jobs.values():
                if job.enabled and job.next_run_at <= now:
                    due_ids.append(job.job_id)

        triggered: list[str] = []
        for jid in due_ids:
            if self.trigger_job(jid):
                triggered.append(jid)

        return triggered
