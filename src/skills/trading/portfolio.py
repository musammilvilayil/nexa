from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping

from .models import RiskSnapshot, TradeSide


@dataclass(frozen=True)
class Position:
    symbol: str
    quantity: int
    average_price: float

    def __post_init__(self) -> None:
        if not self.symbol.strip():
            raise ValueError("symbol required")
        if self.quantity == 0:
            raise ValueError("position quantity cannot be zero")
        if not math.isfinite(self.average_price) or self.average_price <= 0:
            raise ValueError("average_price must be positive and finite")
        object.__setattr__(self, "symbol", self.symbol.strip().upper())


@dataclass(frozen=True)
class FillEffect:
    realized_pnl: float
    position: Position | None


class PaperPortfolio:
    """Deterministic signed-quantity paper portfolio.

    Positive quantity is long, negative quantity is short. Fees are deducted from
    realized PnL immediately so performance metrics never ignore execution cost.

    The optional constructor state exists for trusted persistence adapters. It is
    validated with the same invariants as live mutations so restart recovery does
    not silently admit malformed positions or PnL values.
    """

    def __init__(
        self,
        *,
        positions: Iterable[Position] = (),
        realized_pnl_today: float = 0.0,
        realized_pnl_total: float = 0.0,
    ) -> None:
        if not math.isfinite(realized_pnl_today):
            raise ValueError("realized_pnl_today must be finite")
        if not math.isfinite(realized_pnl_total):
            raise ValueError("realized_pnl_total must be finite")

        restored: dict[str, Position] = {}
        for position in positions:
            if not isinstance(position, Position):
                raise TypeError("positions must contain Position values")
            if position.symbol in restored:
                raise ValueError(f"duplicate position for {position.symbol}")
            restored[position.symbol] = position

        self._positions = restored
        self._realized_pnl_today = float(realized_pnl_today)
        self._realized_pnl_total = float(realized_pnl_total)

    @property
    def positions(self) -> tuple[Position, ...]:
        return tuple(self._positions[symbol] for symbol in sorted(self._positions))

    @property
    def realized_pnl_today(self) -> float:
        return self._realized_pnl_today

    @property
    def realized_pnl_total(self) -> float:
        return self._realized_pnl_total

    def position_quantity(self, symbol: str) -> int:
        position = self._positions.get(symbol.strip().upper())
        return 0 if position is None else position.quantity

    def reset_daily_pnl(self) -> None:
        self._realized_pnl_today = 0.0

    def apply_fill(
        self,
        symbol: str,
        side: TradeSide,
        quantity: int,
        fill_price: float,
        fee: float = 0.0,
    ) -> FillEffect:
        symbol = symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol required")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if not math.isfinite(fill_price) or fill_price <= 0:
            raise ValueError("fill_price must be positive and finite")
        if not math.isfinite(fee) or fee < 0:
            raise ValueError("fee must be finite and non-negative")

        delta = quantity if side == TradeSide.BUY else -quantity
        current = self._positions.get(symbol)
        realized = -fee

        if current is None:
            new_position = Position(symbol, delta, fill_price)
            self._positions[symbol] = new_position
            self._add_realized(realized)
            return FillEffect(realized, new_position)

        current_qty = current.quantity
        if (current_qty > 0 and delta > 0) or (current_qty < 0 and delta < 0):
            total_abs = abs(current_qty) + abs(delta)
            weighted = ((abs(current_qty) * current.average_price) + (abs(delta) * fill_price)) / total_abs
            new_position = Position(symbol, current_qty + delta, weighted)
            self._positions[symbol] = new_position
            self._add_realized(realized)
            return FillEffect(realized, new_position)

        closing_qty = min(abs(current_qty), abs(delta))
        if current_qty > 0:
            realized += (fill_price - current.average_price) * closing_qty
        else:
            realized += (current.average_price - fill_price) * closing_qty

        new_qty = current_qty + delta
        if new_qty == 0:
            self._positions.pop(symbol, None)
            new_position = None
        elif (current_qty > 0 > new_qty) or (current_qty < 0 < new_qty):
            new_position = Position(symbol, new_qty, fill_price)
            self._positions[symbol] = new_position
        else:
            new_position = Position(symbol, new_qty, current.average_price)
            self._positions[symbol] = new_position

        self._add_realized(realized)
        return FillEffect(realized, new_position)

    def market_value(self, prices: Mapping[str, float]) -> float:
        total = 0.0
        for symbol, position in self._positions.items():
            price = float(prices.get(symbol, position.average_price))
            if not math.isfinite(price) or price <= 0:
                raise ValueError(f"invalid market price for {symbol}")
            total += abs(position.quantity) * price
        return total

    def unrealized_pnl(self, prices: Mapping[str, float]) -> float:
        total = 0.0
        for symbol, position in self._positions.items():
            price = float(prices.get(symbol, position.average_price))
            if position.quantity > 0:
                total += (price - position.average_price) * position.quantity
            else:
                total += (position.average_price - price) * abs(position.quantity)
        return total

    def snapshot(self, prices: Mapping[str, float] | None = None) -> RiskSnapshot:
        prices = prices or {}
        quantities = tuple((position.symbol, position.quantity) for position in self.positions)
        return RiskSnapshot(
            total_exposure=self.market_value(prices),
            realized_pnl_today=self.realized_pnl_today,
            open_positions=len(self._positions),
            open_symbols=tuple(position.symbol for position in self.positions),
            position_quantities=quantities,
        )

    def _add_realized(self, amount: float) -> None:
        self._realized_pnl_today += amount
        self._realized_pnl_total += amount
