from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from uuid import uuid4

from sqlite_utils import connect_sqlite

from .models import OrderStatus, TradeSide
from .promotion import PaperEvidence


@dataclass(frozen=True)
class PaperEvidenceReport:
    """Promotion-facing paper evidence plus integrity metadata.

    ``consistent`` is deliberately separate from ``PaperEvidence`` so callers
    cannot mistake an incomplete reconstruction for promotion-quality evidence.
    A live-eligibility workflow should require both a passing promotion decision
    and a consistent evidence report.
    """

    session_id: str
    started_at_utc: datetime
    evidence: PaperEvidence
    consistent: bool
    reasons: tuple[str, ...]


class PaperEvidenceStore:
    """Persistent evidence ledger for autonomous paper trading.

    Evidence is session-scoped. Starting a new session never deletes old orders
    or prior evidence; it only creates a fresh evaluation boundary. Trading days
    are counted from successful autonomous market cycles, while operational
    failures are stored as safety violations. Closed-trade PnL and drawdown are
    reconstructed from persisted filled paper orders after the session boundary.

    Drawdown is based on the realized fill-equity curve. It intentionally does
    not claim intrabar mark-to-market drawdown; later validation can add a richer
    market-value series without changing the promotion safety boundary.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        initial_equity: float = 100_000.0,
    ) -> None:
        if not math.isfinite(initial_equity) or initial_equity <= 0:
            raise ValueError("initial_equity must be positive and finite")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.initial_equity = float(initial_equity)
        self._initialize()
        self._ensure_active_session()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_evidence_sessions (
                    session_id TEXT PRIMARY KEY,
                    started_at_utc TEXT NOT NULL,
                    ended_at_utc TEXT,
                    started_flat INTEGER NOT NULL,
                    note TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_evidence_active (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    session_id TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_evidence_activity (
                    session_id TEXT NOT NULL,
                    trading_date TEXT NOT NULL,
                    cycles INTEGER NOT NULL,
                    PRIMARY KEY(session_id, trading_date)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_safety_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    trading_date TEXT NOT NULL,
                    created_at_utc TEXT NOT NULL,
                    reason TEXT NOT NULL
                )
                """
            )

    def _paper_positions_exist(self, connection: sqlite3.Connection) -> bool:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_positions'"
        ).fetchone()
        if table is None:
            return False
        row = connection.execute("SELECT 1 FROM paper_positions LIMIT 1").fetchone()
        return row is not None

    def _create_session(self, connection: sqlite3.Connection, note: str) -> str:
        session_id = uuid4().hex
        now = datetime.now(timezone.utc).isoformat()
        started_flat = 0 if self._paper_positions_exist(connection) else 1
        connection.execute(
            """
            INSERT INTO paper_evidence_sessions(
                session_id, started_at_utc, ended_at_utc, started_flat, note
            ) VALUES (?, ?, NULL, ?, ?)
            """,
            (session_id, now, started_flat, note.strip()),
        )
        connection.execute(
            """
            INSERT INTO paper_evidence_active(singleton, session_id)
            VALUES (1, ?)
            ON CONFLICT(singleton) DO UPDATE SET session_id=excluded.session_id
            """,
            (session_id,),
        )
        return session_id

    def _ensure_active_session(self) -> str:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT session_id FROM paper_evidence_active WHERE singleton = 1"
            ).fetchone()
            if row is not None:
                return str(row["session_id"])
            return self._create_session(connection, "automatic initial paper evidence session")

    @property
    def active_session_id(self) -> str:
        return self._ensure_active_session()

    def start_new_session(self, note: str = "owner-started paper evidence session") -> str:
        message = note.strip()
        if not message:
            raise ValueError("paper evidence session note required")
        with self._connect() as connection:
            active = connection.execute(
                "SELECT session_id FROM paper_evidence_active WHERE singleton = 1"
            ).fetchone()
            now = datetime.now(timezone.utc).isoformat()
            if active is not None:
                connection.execute(
                    "UPDATE paper_evidence_sessions SET ended_at_utc = ? WHERE session_id = ? AND ended_at_utc IS NULL",
                    (now, str(active["session_id"])),
                )
            return self._create_session(connection, message)

    def record_activity(self, trading_date: date) -> None:
        session_id = self.active_session_id
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO paper_evidence_activity(session_id, trading_date, cycles)
                VALUES (?, ?, 1)
                ON CONFLICT(session_id, trading_date) DO UPDATE SET
                    cycles=paper_evidence_activity.cycles + 1
                """,
                (session_id, trading_date.isoformat()),
            )

    def record_safety_violation(self, trading_date: date, reason: str) -> None:
        message = reason.strip()
        if not message:
            raise ValueError("safety violation reason required")
        session_id = self.active_session_id
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO paper_safety_events(
                    session_id, trading_date, created_at_utc, reason
                ) VALUES (?, ?, ?, ?)
                """,
                (session_id, trading_date.isoformat(), now, message),
            )

    def report(self) -> PaperEvidenceReport:
        session_id = self.active_session_id
        with self._connect() as connection:
            session = connection.execute(
                """
                SELECT started_at_utc, started_flat
                FROM paper_evidence_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if session is None:
                raise RuntimeError("active paper evidence session is missing")

            trading_days = int(
                connection.execute(
                    "SELECT COUNT(*) AS n FROM paper_evidence_activity WHERE session_id = ?",
                    (session_id,),
                ).fetchone()["n"]
            )
            safety_violations = int(
                connection.execute(
                    "SELECT COUNT(*) AS n FROM paper_safety_events WHERE session_id = ?",
                    (session_id,),
                ).fetchone()["n"]
            )

            started_at = datetime.fromisoformat(str(session["started_at_utc"]))
            has_orders_table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='paper_orders'"
            ).fetchone()
            if has_orders_table is None:
                rows = []
            else:
                rows = connection.execute(
                    """
                    SELECT created_at_utc, symbol, side, quantity, fill_price, fee
                    FROM paper_orders
                    WHERE status = ? AND created_at_utc >= ?
                    ORDER BY created_at_utc, order_id
                    """,
                    (OrderStatus.FILLED.value, started_at.isoformat()),
                ).fetchall()

        reasons: list[str] = []
        if not bool(session["started_flat"]):
            reasons.append("paper evidence session began with an open position")

        positions: dict[str, tuple[int, float]] = {}
        cumulative_pnl = 0.0
        closed_trades = 0
        peak_equity = self.initial_equity
        max_drawdown_pct = 0.0

        for row in rows:
            fill_raw = row["fill_price"]
            if fill_raw is None:
                reasons.append("filled paper order is missing fill price")
                continue

            symbol = str(row["symbol"]).strip().upper()
            side = TradeSide(str(row["side"]))
            quantity = int(row["quantity"])
            fill_price = float(fill_raw)
            fee = float(row["fee"])

            if quantity <= 0 or not math.isfinite(fill_price) or fill_price <= 0 or fee < 0:
                reasons.append("paper order ledger contains invalid fill data")
                continue

            delta = quantity if side == TradeSide.BUY else -quantity
            current = positions.get(symbol)
            realized = -fee

            if current is None:
                positions[symbol] = (delta, fill_price)
            else:
                current_qty, average_price = current
                same_direction = (current_qty > 0 and delta > 0) or (current_qty < 0 and delta < 0)
                if same_direction:
                    total_abs = abs(current_qty) + abs(delta)
                    weighted = (
                        abs(current_qty) * average_price + abs(delta) * fill_price
                    ) / total_abs
                    positions[symbol] = (current_qty + delta, weighted)
                else:
                    closing_qty = min(abs(current_qty), abs(delta))
                    if current_qty > 0:
                        realized += (fill_price - average_price) * closing_qty
                    else:
                        realized += (average_price - fill_price) * closing_qty

                    new_qty = current_qty + delta
                    if new_qty == 0:
                        closed_trades += 1
                        positions.pop(symbol, None)
                    elif (current_qty > 0 > new_qty) or (current_qty < 0 < new_qty):
                        closed_trades += 1
                        positions[symbol] = (new_qty, fill_price)
                    else:
                        positions[symbol] = (new_qty, average_price)

            cumulative_pnl += realized
            equity = self.initial_equity + cumulative_pnl
            peak_equity = max(peak_equity, equity)
            if peak_equity > 0:
                drawdown_pct = max(0.0, (peak_equity - equity) / peak_equity * 100.0)
                max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        evidence = PaperEvidence(
            trading_days=trading_days,
            closed_trades=closed_trades,
            net_pnl=cumulative_pnl,
            max_drawdown_pct=max_drawdown_pct,
            safety_violations=safety_violations,
        )
        consistent = not reasons
        return PaperEvidenceReport(
            session_id=session_id,
            started_at_utc=started_at.astimezone(timezone.utc),
            evidence=evidence,
            consistent=consistent,
            reasons=tuple(reasons) if reasons else ("paper evidence ledger reconstructed successfully",),
        )
