from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class TradeSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


class TradingMode(str, Enum):
    RESEARCH = "research"
    PAPER_AUTONOMOUS = "paper_autonomous"
    LIVE_SUPERVISED = "live_supervised"
    LIVE_AUTONOMOUS = "live_autonomous"


class OrderStatus(str, Enum):
    FILLED = "filled"
    REJECTED = "rejected"


def _positive_finite(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True)
class TradingMandate:
    """Owner-defined envelope that trading logic may never exceed."""

    mode: TradingMode
    allowed_symbols: tuple[str, ...]
    max_notional_per_trade: float
    max_total_exposure: float
    max_risk_per_trade: float
    max_daily_loss: float
    max_open_positions: int
    min_signal_confidence: float = 0.55
    allow_short: bool = False
    require_stop_loss: bool = True

    def __post_init__(self) -> None:
        symbols = tuple(sorted({symbol.strip().upper() for symbol in self.allowed_symbols if symbol.strip()}))
        if not symbols:
            raise ValueError("allowed_symbols cannot be empty")
        object.__setattr__(self, "allowed_symbols", symbols)

        _positive_finite("max_notional_per_trade", self.max_notional_per_trade)
        _positive_finite("max_total_exposure", self.max_total_exposure)
        _positive_finite("max_risk_per_trade", self.max_risk_per_trade)
        _positive_finite("max_daily_loss", self.max_daily_loss)
        if self.max_open_positions <= 0:
            raise ValueError("max_open_positions must be positive")
        if not 0.0 <= self.min_signal_confidence <= 1.0:
            raise ValueError("min_signal_confidence must be between 0 and 1")


@dataclass(frozen=True)
class TradeSignal:
    symbol: str
    side: TradeSide
    price: float
    confidence: float
    strategy_id: str
    stop_loss: float | None = None
    take_profit: float | None = None

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        strategy_id = self.strategy_id.strip()
        if not symbol:
            raise ValueError("symbol required")
        if not strategy_id:
            raise ValueError("strategy_id required")
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "strategy_id", strategy_id)

        _positive_finite("price", self.price)
        if self.stop_loss is not None:
            _positive_finite("stop_loss", self.stop_loss)
        if self.take_profit is not None:
            _positive_finite("take_profit", self.take_profit)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True)
class RiskSnapshot:
    total_exposure: float = 0.0
    realized_pnl_today: float = 0.0
    open_positions: int = 0
    open_symbols: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.total_exposure) or self.total_exposure < 0:
            raise ValueError("total_exposure must be finite and non-negative")
        if not math.isfinite(self.realized_pnl_today):
            raise ValueError("realized_pnl_today must be finite")
        if self.open_positions < 0:
            raise ValueError("open_positions cannot be negative")
        object.__setattr__(self, "open_symbols", tuple(symbol.upper() for symbol in self.open_symbols))


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reason: str
    approved_quantity: int = 0


@dataclass(frozen=True)
class PaperOrder:
    order_id: str
    symbol: str
    side: TradeSide
    quantity: int
    requested_price: float
    fill_price: float | None
    fee: float
    status: OrderStatus
    reason: str
