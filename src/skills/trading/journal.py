from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


class TradingJournal:
    """SQLite append-only journal for trading decisions and evaluations."""

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
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trading_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    symbol TEXT,
                    strategy_id TEXT,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_trading_events_time ON trading_events(timestamp_utc)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_trading_events_symbol ON trading_events(symbol)"
            )

    def record(
        self,
        event_type: str,
        status: str,
        payload: Any,
        *,
        symbol: str | None = None,
        strategy_id: str | None = None,
    ) -> int:
        event_type = event_type.strip()
        status = status.strip()
        if not event_type or not status:
            raise ValueError("event_type and status are required")
        timestamp = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(_json_safe(payload), sort_keys=True, separators=(",", ":"))
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO trading_events(
                    timestamp_utc, event_type, symbol, strategy_id, status, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    event_type,
                    symbol.strip().upper() if symbol else None,
                    strategy_id.strip() if strategy_id else None,
                    status,
                    payload_json,
                ),
            )
            return int(cursor.lastrowid)

    def recent(self, limit: int = 100) -> tuple[dict[str, Any], ...]:
        if limit <= 0 or limit > 10_000:
            raise ValueError("limit must be between 1 and 10000")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM trading_events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return tuple(
            {
                "id": row["id"],
                "timestamp_utc": row["timestamp_utc"],
                "event_type": row["event_type"],
                "symbol": row["symbol"],
                "strategy_id": row["strategy_id"],
                "status": row["status"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        )


def _json_safe(value: Any) -> Any:
    if is_dataclass(value):
        return _json_safe(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return repr(value)
