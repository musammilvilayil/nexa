from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Mapping

from sqlite_utils import connect_sqlite

from .models import OrderStatus, PaperOrder, TradeSide, TradeSignal
from .portfolio import PaperPortfolio, Position


@dataclass(frozen=True)
class PaperRuntimeState:
    portfolio: PaperPortfolio
    orders: tuple[PaperOrder, ...]
    last_processed: tuple[tuple[str, datetime], ...]
    protective_signals: tuple[tuple[str, TradeSignal], ...]
    trading_date: date | None


class PaperStateStore:
    """SQLite persistence for autonomous paper execution.

    The store keeps simulated orders, current positions/PnL, duplicate-bar
    protection, and protective stop/target context. It is deliberately local and
    contains no live-broker credentials or live authorization state.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return connect_sqlite(self.db_path)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_orders (
                    order_id TEXT PRIMARY KEY,
                    created_at_utc TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    side TEXT NOT NULL,
                    quantity INTEGER NOT NULL,
                    requested_price REAL NOT NULL,
                    fill_price REAL,
                    fee REAL NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    confidence REAL,
                    strategy_id TEXT,
                    stop_loss REAL,
                    take_profit REAL,
                    generated_at_utc TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_positions (
                    symbol TEXT PRIMARY KEY,
                    quantity INTEGER NOT NULL,
                    average_price REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_runtime_state (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    realized_pnl_today REAL NOT NULL,
                    realized_pnl_total REAL NOT NULL,
                    trading_date TEXT,
                    last_processed_json TEXT NOT NULL,
                    protective_json TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL
                )
                """
            )

    def load(self) -> PaperRuntimeState:
        with self._connect() as connection:
            position_rows = connection.execute(
                "SELECT symbol, quantity, average_price FROM paper_positions ORDER BY symbol"
            ).fetchall()
            state_row = connection.execute(
                """
                SELECT realized_pnl_today, realized_pnl_total, trading_date,
                       last_processed_json, protective_json
                FROM paper_runtime_state
                WHERE singleton = 1
                """
            ).fetchone()
            order_rows = connection.execute(
                """
                SELECT order_id, symbol, side, quantity, requested_price, fill_price,
                       fee, status, reason
                FROM paper_orders
                ORDER BY created_at_utc, order_id
                """
            ).fetchall()

        positions = tuple(
            Position(
                symbol=str(row["symbol"]),
                quantity=int(row["quantity"]),
                average_price=float(row["average_price"]),
            )
            for row in position_rows
        )

        realized_today = 0.0
        realized_total = 0.0
        trading_date: date | None = None
        last_processed: tuple[tuple[str, datetime], ...] = ()
        protective: tuple[tuple[str, TradeSignal], ...] = ()

        if state_row is not None:
            realized_today = float(state_row["realized_pnl_today"])
            realized_total = float(state_row["realized_pnl_total"])
            raw_date = state_row["trading_date"]
            trading_date = date.fromisoformat(str(raw_date)) if raw_date else None
            last_processed = self._decode_last_processed(str(state_row["last_processed_json"]))
            protective = self._decode_protective(str(state_row["protective_json"]))

        portfolio = PaperPortfolio(
            positions=positions,
            realized_pnl_today=realized_today,
            realized_pnl_total=realized_total,
        )
        orders = tuple(self._row_to_order(row) for row in order_rows)

        # Recovery fallback: an open paper position must not lose its protective
        # stop/target merely because the previous process died between the fill
        # and the metadata checkpoint. Reconstruct from the latest filled entry
        # signal stored with the order when necessary.
        protective_map = dict(protective)
        for position in portfolio.positions:
            if position.symbol not in protective_map:
                signal = self._latest_entry_signal(position.symbol)
                if signal is not None:
                    protective_map[position.symbol] = signal

        return PaperRuntimeState(
            portfolio=portfolio,
            orders=orders,
            last_processed=last_processed,
            protective_signals=tuple(sorted(protective_map.items())),
            trading_date=trading_date,
        )

    def record_order(
        self,
        order: PaperOrder,
        signal: TradeSignal,
        portfolio: PaperPortfolio,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        generated = signal.generated_at_utc.isoformat() if signal.generated_at_utc else None
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO paper_orders(
                    order_id, created_at_utc, symbol, side, quantity,
                    requested_price, fill_price, fee, status, reason,
                    confidence, strategy_id, stop_loss, take_profit, generated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.order_id,
                    now,
                    order.symbol,
                    order.side.value,
                    order.quantity,
                    order.requested_price,
                    order.fill_price,
                    order.fee,
                    order.status.value,
                    order.reason,
                    signal.confidence,
                    signal.strategy_id,
                    signal.stop_loss,
                    signal.take_profit,
                    generated,
                ),
            )
            self._replace_positions(connection, portfolio)
            self._upsert_pnl_only(connection, portfolio, now)

    def save_runtime(
        self,
        *,
        portfolio: PaperPortfolio,
        last_processed: Mapping[str, datetime],
        protective_signals: Mapping[str, TradeSignal],
        trading_date: date | None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        last_json = self._encode_last_processed(last_processed)
        protective_json = self._encode_protective(protective_signals)
        with self._connect() as connection:
            self._replace_positions(connection, portfolio)
            connection.execute(
                """
                INSERT INTO paper_runtime_state(
                    singleton, realized_pnl_today, realized_pnl_total, trading_date,
                    last_processed_json, protective_json, updated_at_utc
                ) VALUES (1, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    realized_pnl_today=excluded.realized_pnl_today,
                    realized_pnl_total=excluded.realized_pnl_total,
                    trading_date=excluded.trading_date,
                    last_processed_json=excluded.last_processed_json,
                    protective_json=excluded.protective_json,
                    updated_at_utc=excluded.updated_at_utc
                """,
                (
                    portfolio.realized_pnl_today,
                    portfolio.realized_pnl_total,
                    trading_date.isoformat() if trading_date else None,
                    last_json,
                    protective_json,
                    now,
                ),
            )

    def _latest_entry_signal(self, symbol: str) -> TradeSignal | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT symbol, side, requested_price, confidence, strategy_id,
                       stop_loss, take_profit, generated_at_utc
                FROM paper_orders
                WHERE symbol = ? AND status = ? AND strategy_id IS NOT NULL
                ORDER BY created_at_utc DESC, order_id DESC
                LIMIT 1
                """,
                (symbol.strip().upper(), OrderStatus.FILLED.value),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_signal(row)

    @staticmethod
    def _replace_positions(connection: sqlite3.Connection, portfolio: PaperPortfolio) -> None:
        connection.execute("DELETE FROM paper_positions")
        connection.executemany(
            "INSERT INTO paper_positions(symbol, quantity, average_price) VALUES (?, ?, ?)",
            [
                (position.symbol, position.quantity, position.average_price)
                for position in portfolio.positions
            ],
        )

    @staticmethod
    def _upsert_pnl_only(
        connection: sqlite3.Connection,
        portfolio: PaperPortfolio,
        updated_at_utc: str,
    ) -> None:
        existing = connection.execute(
            "SELECT trading_date, last_processed_json, protective_json FROM paper_runtime_state WHERE singleton = 1"
        ).fetchone()
        trading_date = existing["trading_date"] if existing is not None else None
        last_json = existing["last_processed_json"] if existing is not None else "{}"
        protective_json = existing["protective_json"] if existing is not None else "{}"
        connection.execute(
            """
            INSERT INTO paper_runtime_state(
                singleton, realized_pnl_today, realized_pnl_total, trading_date,
                last_processed_json, protective_json, updated_at_utc
            ) VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                realized_pnl_today=excluded.realized_pnl_today,
                realized_pnl_total=excluded.realized_pnl_total,
                updated_at_utc=excluded.updated_at_utc
            """,
            (
                portfolio.realized_pnl_today,
                portfolio.realized_pnl_total,
                trading_date,
                last_json,
                protective_json,
                updated_at_utc,
            ),
        )

    @staticmethod
    def _row_to_order(row: sqlite3.Row) -> PaperOrder:
        fill_price = row["fill_price"]
        return PaperOrder(
            order_id=str(row["order_id"]),
            symbol=str(row["symbol"]),
            side=TradeSide(str(row["side"])),
            quantity=int(row["quantity"]),
            requested_price=float(row["requested_price"]),
            fill_price=None if fill_price is None else float(fill_price),
            fee=float(row["fee"]),
            status=OrderStatus(str(row["status"])),
            reason=str(row["reason"]),
        )

    @staticmethod
    def _row_to_signal(row: sqlite3.Row) -> TradeSignal:
        generated_raw = row["generated_at_utc"]
        generated = datetime.fromisoformat(str(generated_raw)) if generated_raw else None
        confidence = row["confidence"]
        strategy_id = row["strategy_id"]
        if confidence is None or strategy_id is None:
            raise ValueError("persisted paper signal is incomplete")
        return TradeSignal(
            symbol=str(row["symbol"]),
            side=TradeSide(str(row["side"])),
            price=float(row["requested_price"]),
            confidence=float(confidence),
            strategy_id=str(strategy_id),
            stop_loss=None if row["stop_loss"] is None else float(row["stop_loss"]),
            take_profit=None if row["take_profit"] is None else float(row["take_profit"]),
            generated_at_utc=generated,
        )

    @staticmethod
    def _encode_last_processed(values: Mapping[str, datetime]) -> str:
        payload: dict[str, str] = {}
        for symbol, timestamp in values.items():
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("last_processed timestamps must be timezone-aware")
            payload[symbol.strip().upper()] = timestamp.astimezone(timezone.utc).isoformat()
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode_last_processed(raw: str) -> tuple[tuple[str, datetime], ...]:
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("invalid persisted last_processed state")
        values: list[tuple[str, datetime]] = []
        for symbol, timestamp_raw in payload.items():
            timestamp = datetime.fromisoformat(str(timestamp_raw))
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("persisted last_processed timestamp must be timezone-aware")
            values.append((str(symbol).strip().upper(), timestamp.astimezone(timezone.utc)))
        return tuple(sorted(values))

    @classmethod
    def _encode_protective(cls, values: Mapping[str, TradeSignal]) -> str:
        payload = {
            symbol.strip().upper(): cls._signal_to_dict(signal)
            for symbol, signal in values.items()
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _decode_protective(cls, raw: str) -> tuple[tuple[str, TradeSignal], ...]:
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise ValueError("invalid persisted protective state")
        values: list[tuple[str, TradeSignal]] = []
        for symbol, signal_payload in payload.items():
            if not isinstance(signal_payload, dict):
                raise ValueError("invalid persisted protective signal")
            signal = cls._dict_to_signal(signal_payload)
            key = str(symbol).strip().upper()
            if signal.symbol != key:
                raise ValueError("persisted protective symbol mismatch")
            values.append((key, signal))
        return tuple(sorted(values))

    @staticmethod
    def _signal_to_dict(signal: TradeSignal) -> dict[str, object]:
        return {
            "symbol": signal.symbol,
            "side": signal.side.value,
            "price": signal.price,
            "confidence": signal.confidence,
            "strategy_id": signal.strategy_id,
            "stop_loss": signal.stop_loss,
            "take_profit": signal.take_profit,
            "generated_at_utc": signal.generated_at_utc.isoformat() if signal.generated_at_utc else None,
        }

    @staticmethod
    def _dict_to_signal(payload: Mapping[str, object]) -> TradeSignal:
        generated_raw = payload.get("generated_at_utc")
        generated = datetime.fromisoformat(str(generated_raw)) if generated_raw else None
        stop_raw = payload.get("stop_loss")
        target_raw = payload.get("take_profit")
        return TradeSignal(
            symbol=str(payload["symbol"]),
            side=TradeSide(str(payload["side"])),
            price=float(payload["price"]),
            confidence=float(payload["confidence"]),
            strategy_id=str(payload["strategy_id"]),
            stop_loss=None if stop_raw is None else float(stop_raw),
            take_profit=None if target_raw is None else float(target_raw),
            generated_at_utc=generated,
        )
