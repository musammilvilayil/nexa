from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from core.contracts import RiskTier
from sqlite_utils import connect_sqlite

from .contracts import (
    CapabilityEvent,
    CapabilityEventType,
    CapabilityRecord,
    CapabilitySpec,
)


class CapabilityStore:
    """Persistent storage for dynamically registered capabilities, versions, and observability events."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capabilities (
                    capability_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    version TEXT NOT NULL,
                    risk_tier TEXT NOT NULL,
                    input_schema TEXT NOT NULL,
                    output_schema TEXT NOT NULL,
                    dependencies TEXT NOT NULL,
                    permissions TEXT NOT NULL,
                    module_path TEXT NOT NULL,
                    class_name TEXT NOT NULL,
                    test_status TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at_utc TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    capability_id TEXT NOT NULL,
                    message TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    details TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_versions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capability_id TEXT NOT NULL,
                    version TEXT NOT NULL,
                    code TEXT NOT NULL,
                    test_code TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL
                )
                """
            )

    def save_capability(
        self,
        record: CapabilityRecord,
        *,
        code: str = "",
        test_code: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO capabilities (
                    capability_id, name, description, purpose, version, risk_tier,
                    input_schema, output_schema, dependencies, permissions,
                    module_path, class_name, test_status, created_at_utc,
                    updated_at_utc, usage_count, last_used_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capability_id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    purpose=excluded.purpose,
                    version=excluded.version,
                    risk_tier=excluded.risk_tier,
                    input_schema=excluded.input_schema,
                    output_schema=excluded.output_schema,
                    dependencies=excluded.dependencies,
                    permissions=excluded.permissions,
                    module_path=excluded.module_path,
                    class_name=excluded.class_name,
                    test_status=excluded.test_status,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (
                    record.spec.capability_id,
                    record.spec.name,
                    record.spec.description,
                    record.spec.purpose,
                    record.spec.version,
                    record.spec.risk_tier.value,
                    json.dumps(record.spec.input_schema),
                    json.dumps(record.spec.output_schema),
                    json.dumps(list(record.spec.dependencies)),
                    json.dumps(list(record.spec.permissions)),
                    record.module_path,
                    record.class_name,
                    record.test_status,
                    record.created_at_utc or now,
                    now,
                    record.usage_count,
                    record.last_used_at_utc,
                ),
            )
            if code:
                conn.execute(
                    """
                    INSERT INTO capability_versions (
                        capability_id, version, code, test_code, timestamp_utc
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        record.spec.capability_id,
                        record.spec.version,
                        code,
                        test_code,
                        now,
                    ),
                )

    def get_capability(self, key: str) -> CapabilityRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM capabilities WHERE capability_id = ? OR name = ?
                """,
                (key, key),
            ).fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    def list_capabilities(self) -> tuple[CapabilityRecord, ...]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM capabilities ORDER BY created_at_utc"
            ).fetchall()
            return tuple(self._row_to_record(row) for row in rows)

    def record_usage(self, key: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE capabilities
                SET usage_count = usage_count + 1, last_used_at_utc = ?
                WHERE capability_id = ? OR name = ?
                """,
                (now, key, key),
            )

    def record_event(self, event: CapabilityEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO capability_events (
                    event_type, capability_id, message, timestamp_utc, details
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.event_type.value,
                    event.capability_id,
                    event.message,
                    event.timestamp_utc,
                    json.dumps(event.details),
                ),
            )

    def get_events(
        self,
        limit: int = 50,
        capability_id: str | None = None,
    ) -> tuple[CapabilityEvent, ...]:
        query = "SELECT * FROM capability_events"
        params: list[Any] = []
        if capability_id:
            query += " WHERE capability_id = ?"
            params.append(capability_id)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            return tuple(
                CapabilityEvent(
                    event_type=CapabilityEventType(row["event_type"]),
                    capability_id=row["capability_id"],
                    message=row["message"],
                    timestamp_utc=row["timestamp_utc"],
                    details=json.loads(row["details"]) if row["details"] else {},
                )
                for row in rows
            )

    def _row_to_record(self, row: sqlite3.Row) -> CapabilityRecord:
        spec = CapabilitySpec(
            capability_id=row["capability_id"],
            name=row["name"],
            description=row["description"],
            purpose=row["purpose"],
            version=row["version"],
            risk_tier=RiskTier(row["risk_tier"]),
            input_schema=json.loads(row["input_schema"]) if row["input_schema"] else {},
            output_schema=json.loads(row["output_schema"]) if row["output_schema"] else {},
            dependencies=tuple(json.loads(row["dependencies"])) if row["dependencies"] else (),
            permissions=tuple(json.loads(row["permissions"])) if row["permissions"] else (),
        )
        return CapabilityRecord(
            spec=spec,
            module_path=row["module_path"],
            class_name=row["class_name"],
            test_status=row["test_status"],
            created_at_utc=row["created_at_utc"],
            updated_at_utc=row["updated_at_utc"],
            usage_count=int(row["usage_count"]),
            last_used_at_utc=row["last_used_at_utc"],
        )
