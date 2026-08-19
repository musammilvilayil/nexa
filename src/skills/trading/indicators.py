from __future__ import annotations

import math
from typing import Sequence

from .market import Candle


def _validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be positive")


def sma(values: Sequence[float], period: int) -> float | None:
    _validate_period(period)
    if len(values) < period:
        return None
    window = values[-period:]
    if any(not math.isfinite(value) for value in window):
        raise ValueError("indicator input contains non-finite value")
    return sum(window) / period


def ema(values: Sequence[float], period: int) -> float | None:
    _validate_period(period)
    if len(values) < period:
        return None
    if any(not math.isfinite(value) for value in values):
        raise ValueError("indicator input contains non-finite value")

    seed = sum(values[:period]) / period
    alpha = 2.0 / (period + 1.0)
    result = seed
    for value in values[period:]:
        result = (value * alpha) + (result * (1.0 - alpha))
    return result


def true_range(current: Candle, previous_close: float | None) -> float:
    if previous_close is None:
        return current.high - current.low
    return max(
        current.high - current.low,
        abs(current.high - previous_close),
        abs(current.low - previous_close),
    )


def atr(candles: Sequence[Candle], period: int) -> float | None:
    _validate_period(period)
    if len(candles) < period + 1:
        return None
    ranges: list[float] = []
    previous_close: float | None = None
    for candle in candles:
        ranges.append(true_range(candle, previous_close))
        previous_close = candle.close
    return sma(ranges, period)


def highest(values: Sequence[float], period: int, *, exclude_last: bool = False) -> float | None:
    _validate_period(period)
    source = values[:-1] if exclude_last else values
    if len(source) < period:
        return None
    window = source[-period:]
    if any(not math.isfinite(value) for value in window):
        raise ValueError("indicator input contains non-finite value")
    return max(window)


def lowest(values: Sequence[float], period: int, *, exclude_last: bool = False) -> float | None:
    _validate_period(period)
    source = values[:-1] if exclude_last else values
    if len(source) < period:
        return None
    window = source[-period:]
    if any(not math.isfinite(value) for value in window):
        raise ValueError("indicator input contains non-finite value")
    return min(window)
