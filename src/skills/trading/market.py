from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone


def _finite_positive(name: str, value: float) -> None:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number")


@dataclass(frozen=True)
class Candle:
    """One validated OHLCV bar.

    Timestamps must be timezone-aware so research, paper trading, and future
    broker adapters cannot silently mix local time with exchange time.
    """

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("candle timestamp must be timezone-aware")
        _finite_positive("open", self.open)
        _finite_positive("high", self.high)
        _finite_positive("low", self.low)
        _finite_positive("close", self.close)
        if not math.isfinite(self.volume) or self.volume < 0:
            raise ValueError("volume must be finite and non-negative")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("high is inconsistent with OHLC values")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("low is inconsistent with OHLC values")

    @property
    def utc_timestamp(self) -> datetime:
        return self.timestamp.astimezone(timezone.utc)


@dataclass(frozen=True)
class MarketSeries:
    symbol: str
    candles: tuple[Candle, ...]

    def __post_init__(self) -> None:
        symbol = self.symbol.strip().upper()
        if not symbol:
            raise ValueError("symbol required")
        if not self.candles:
            raise ValueError("market series requires at least one candle")
        object.__setattr__(self, "symbol", symbol)

        previous = None
        for candle in self.candles:
            current = candle.utc_timestamp
            if previous is not None and current <= previous:
                raise ValueError("candle timestamps must be strictly increasing")
            previous = current

    def tail(self, count: int) -> "MarketSeries":
        if count <= 0:
            raise ValueError("count must be positive")
        return MarketSeries(self.symbol, self.candles[-count:])

    def upto(self, end_exclusive: int) -> "MarketSeries":
        if end_exclusive <= 0 or end_exclusive > len(self.candles):
            raise ValueError("end_exclusive outside series")
        return MarketSeries(self.symbol, self.candles[:end_exclusive])

    @property
    def closes(self) -> tuple[float, ...]:
        return tuple(candle.close for candle in self.candles)

    @property
    def highs(self) -> tuple[float, ...]:
        return tuple(candle.high for candle in self.candles)

    @property
    def lows(self) -> tuple[float, ...]:
        return tuple(candle.low for candle in self.candles)

    @property
    def volumes(self) -> tuple[float, ...]:
        return tuple(candle.volume for candle in self.candles)

    @property
    def last(self) -> Candle:
        return self.candles[-1]


@dataclass(frozen=True)
class DataQualityReport:
    valid: bool
    bars: int
    stale: bool
    reason: str = ""


def validate_market_series(
    series: MarketSeries,
    *,
    now: datetime | None = None,
    max_age_seconds: float | None = None,
    min_bars: int = 1,
) -> DataQualityReport:
    if min_bars <= 0:
        raise ValueError("min_bars must be positive")
    if len(series.candles) < min_bars:
        return DataQualityReport(False, len(series.candles), False, "insufficient bars")

    stale = False
    if max_age_seconds is not None:
        if not math.isfinite(max_age_seconds) or max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive and finite")
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        age = (current.astimezone(timezone.utc) - series.last.utc_timestamp).total_seconds()
        stale = age > max_age_seconds
        if stale:
            return DataQualityReport(False, len(series.candles), True, "market data is stale")

    return DataQualityReport(True, len(series.candles), stale, "ok")
