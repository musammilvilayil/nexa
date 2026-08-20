from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping, Protocol


class AuditStatus(str, Enum):
    PENDING = "pending"
    STARTED = "started"
    SUCCESS = "success"
    FAILURE = "failure"
    DENIED = "denied"
    VALIDATION_FAILED = "validation_failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


@dataclass(frozen=True)
class AuditEntry:
    action_id: str
    timestamp_utc: str
    updated_at_utc: str
    skill_name: str
    operation: str
    params: Any
    risk_tier: str
    status: AuditStatus
    confirmed: bool
    result: Any
    error: str | None


class AuditLedger(Protocol):
    def record(
        self,
        *,
        action_id: str,
        skill_name: str,
        operation: str,
        params: Mapping[str, Any],
        risk_tier: str,
        status: AuditStatus,
        confirmed: bool = False,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        ...


class SQLiteAuditLedger:
    """Persistent action ledger for the standalone kernel.

    Rows are upserted by action_id so a pending/started action becomes a final
    success, failure, cancellation, or expiry record without losing the original
    validated parameters. Common secret-shaped keys are redacted before JSON
    serialization.
    """

    DEFAULT_REDACT_FRAGMENTS = (
        "api_key",
        "apikey",
        "authorization",
        "password",
        "secret",
        "token",
    )

    def __init__(
        self,
        db_path: str | Path,
        *,
        redact_fragments: tuple[str, ...] | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.redact_fragments = tuple(
            item.lower() for item in (redact_fragments or self.DEFAULT_REDACT_FRAGMENTS)
        )
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
                CREATE TABLE IF NOT EXISTS actions (
                    action_id TEXT PRIMARY KEY,
                    timestamp_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    skill_name TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    params_json TEXT NOT NULL,
                    risk_tier TEXT NOT NULL,
                    status TEXT NOT NULL,
                    confirmed INTEGER NOT NULL,
                    result_json TEXT,
                    error TEXT
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_actions_time ON actions(updated_at_utc)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_actions_skill ON actions(skill_name, operation)"
            )

    def record(
        self,
        *,
        action_id: str,
        skill_name: str,
        operation: str,
        params: Mapping[str, Any],
        risk_tier: str,
        status: AuditStatus,
        confirmed: bool = False,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        action_id = action_id.strip()
        if not action_id:
            raise ValueError("action_id required")
        now = datetime.now(timezone.utc).isoformat()
        params_json = json.dumps(self._safe(params), sort_keys=True, separators=(",", ":"))
        result_json = None if result is None else json.dumps(
            self._safe(result), sort_keys=True, separators=(",", ":")
        )

        with self._connect() as connection:
            existing = connection.execute(
                "SELECT timestamp_utc FROM actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
            created = existing["timestamp_utc"] if existing is not None else now
            connection.execute(
                """
                INSERT INTO actions(
                    action_id, timestamp_utc, updated_at_utc, skill_name,
                    operation, params_json, risk_tier, status, confirmed,
                    result_json, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    updated_at_utc=excluded.updated_at_utc,
                    skill_name=excluded.skill_name,
                    operation=excluded.operation,
                    params_json=excluded.params_json,
                    risk_tier=excluded.risk_tier,
                    status=excluded.status,
                    confirmed=excluded.confirmed,
                    result_json=excluded.result_json,
                    error=excluded.error
                """,
                (
                    action_id,
                    created,
                    now,
                    skill_name,
                    operation,
                    params_json,
                    risk_tier,
                    status.value,
                    1 if confirmed else 0,
                    result_json,
                    error,
                ),
            )

    def get(self, action_id: str) -> AuditEntry | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        return None if row is None else self._entry(row)

    def recent(self, limit: int = 100) -> tuple[AuditEntry, ...]:
        if limit <= 0 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM actions ORDER BY updated_at_utc DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(self._entry(row) for row in rows)

    def _entry(self, row: sqlite3.Row) -> AuditEntry:
        return AuditEntry(
            action_id=row["action_id"],
            timestamp_utc=row["timestamp_utc"],
            updated_at_utc=row["updated_at_utc"],
            skill_name=row["skill_name"],
            operation=row["operation"],
            params=json.loads(row["params_json"]),
            risk_tier=row["risk_tier"],
            status=AuditStatus(row["status"]),
            confirmed=bool(row["confirmed"]),
            result=None if row["result_json"] is None else json.loads(row["result_json"]),
            error=row["error"],
        )

    def _safe(self, value: Any, *, key: str | None = None) -> Any:
        if key is not None and any(fragment in key.lower() for fragment in self.redact_fragments):
            return "<redacted>"
        if is_dataclass(value):
            return self._safe(asdict(value))
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, Mapping):
            return {str(item_key): self._safe(item, key=str(item_key)) for item_key, item in value.items()}
        if isinstance(value, (tuple, list, set)):
            return [self._safe(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return repr(value)
