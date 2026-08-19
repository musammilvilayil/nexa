from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .indicators import atr, ema
from .market import MarketSeries


class MarketRegime(str, Enum):
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    UNCERTAIN = "uncertain"


@dataclass(frozen=True)
class RegimeReading:
    regime: MarketRegime
    trend_strength: float
    volatility_ratio: float
    reason: str


@dataclass(frozen=True)
class RegimeConfig:
    fast_ema: int = 10
    slow_ema: int = 30
    atr_period: int = 14
    trend_threshold: float = 0.0025
    range_threshold: float = 0.0010
    max_volatility_ratio: float = 0.08

    def __post_init__(self) -> None:
        if self.fast_ema <= 0 or self.slow_ema <= 0 or self.atr_period <= 0:
            raise ValueError("indicator periods must be positive")
        if self.fast_ema >= self.slow_ema:
            raise ValueError("fast_ema must be smaller than slow_ema")
        if self.trend_threshold <= 0 or self.range_threshold < 0:
            raise ValueError("regime thresholds must be non-negative")
        if self.range_threshold >= self.trend_threshold:
            raise ValueError("range_threshold must be below trend_threshold")
        if self.max_volatility_ratio <= 0:
            raise ValueError("max_volatility_ratio must be positive")


class RegimeDetector:
    def __init__(self, config: RegimeConfig | None = None) -> None:
        self.config = config or RegimeConfig()

    @property
    def minimum_bars(self) -> int:
        return max(self.config.slow_ema, self.config.atr_period + 1)

    def detect(self, series: MarketSeries) -> RegimeReading:
        if len(series.candles) < self.minimum_bars:
            return RegimeReading(MarketRegime.UNCERTAIN, 0.0, 0.0, "insufficient bars")

        fast = ema(series.closes, self.config.fast_ema)
        slow = ema(series.closes, self.config.slow_ema)
        current_atr = atr(series.candles, self.config.atr_period)
        if fast is None or slow is None or current_atr is None:
            return RegimeReading(MarketRegime.UNCERTAIN, 0.0, 0.0, "indicator unavailable")

        price = series.last.close
        trend_strength = abs(fast - slow) / price
        volatility_ratio = current_atr / price

        if volatility_ratio > self.config.max_volatility_ratio:
            return RegimeReading(
                MarketRegime.UNCERTAIN,
                trend_strength,
                volatility_ratio,
                "volatility exceeds regime safety threshold",
            )

        if trend_strength >= self.config.trend_threshold:
            regime = MarketRegime.TRENDING_UP if fast > slow else MarketRegime.TRENDING_DOWN
            return RegimeReading(regime, trend_strength, volatility_ratio, "ema separation confirms trend")

        if trend_strength <= self.config.range_threshold:
            return RegimeReading(MarketRegime.RANGING, trend_strength, volatility_ratio, "ema separation is compressed")

        return RegimeReading(MarketRegime.UNCERTAIN, trend_strength, volatility_ratio, "regime transition zone")
