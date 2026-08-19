from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .indicators import atr, highest, lowest, sma
from .market import MarketSeries
from .models import TradeSide, TradeSignal
from .regime import MarketRegime, RegimeDetector, RegimeReading


@dataclass(frozen=True)
class StrategyDecision:
    signal: TradeSignal | None
    regime: RegimeReading
    reason: str


class Strategy(Protocol):
    @property
    def strategy_id(self) -> str:
        ...

    @property
    def minimum_bars(self) -> int:
        ...

    def evaluate(self, series: MarketSeries) -> StrategyDecision:
        ...


@dataclass(frozen=True)
class MomentumConfig:
    breakout_lookback: int = 20
    atr_period: int = 14
    stop_atr_multiple: float = 1.5
    reward_to_risk: float = 2.0
    minimum_breakout_fraction: float = 0.0005
    allow_short_signals: bool = True

    def __post_init__(self) -> None:
        if self.breakout_lookback <= 1 or self.atr_period <= 1:
            raise ValueError("lookback periods must be greater than one")
        if self.stop_atr_multiple <= 0 or self.reward_to_risk <= 0:
            raise ValueError("risk multipliers must be positive")
        if self.minimum_breakout_fraction < 0:
            raise ValueError("minimum_breakout_fraction cannot be negative")


class AdaptiveMomentumStrategy:
    """Trend-following breakout strategy used as NEXA's first research baseline.

    It intentionally returns no trade outside a confirmed trend. Profitability is
    not assumed; the strategy must pass out-of-sample evaluation before promotion.
    """

    def __init__(
        self,
        config: MomentumConfig | None = None,
        regime_detector: RegimeDetector | None = None,
    ) -> None:
        self.config = config or MomentumConfig()
        self.regime_detector = regime_detector or RegimeDetector()
        self._strategy_id = "adaptive_momentum_v1"

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def minimum_bars(self) -> int:
        return max(
            self.config.breakout_lookback + 1,
            self.config.atr_period + 1,
            self.regime_detector.minimum_bars,
        )

    def evaluate(self, series: MarketSeries) -> StrategyDecision:
        regime = self.regime_detector.detect(series)
        if len(series.candles) < self.minimum_bars:
            return StrategyDecision(None, regime, "insufficient bars")

        current_atr = atr(series.candles, self.config.atr_period)
        prior_high = highest(series.highs, self.config.breakout_lookback, exclude_last=True)
        prior_low = lowest(series.lows, self.config.breakout_lookback, exclude_last=True)
        if current_atr is None or prior_high is None or prior_low is None:
            return StrategyDecision(None, regime, "indicator unavailable")

        price = series.last.close
        if regime.regime == MarketRegime.TRENDING_UP:
            breakout_fraction = max(0.0, (price - prior_high) / prior_high)
            if price <= prior_high or breakout_fraction < self.config.minimum_breakout_fraction:
                return StrategyDecision(None, regime, "uptrend present but breakout not confirmed")
            risk_distance = current_atr * self.config.stop_atr_multiple
            stop = price - risk_distance
            target = price + (risk_distance * self.config.reward_to_risk)
            confidence = self._confidence(regime, breakout_fraction)
            return StrategyDecision(
                TradeSignal(
                    symbol=series.symbol,
                    side=TradeSide.BUY,
                    price=price,
                    stop_loss=stop,
                    take_profit=target,
                    confidence=confidence,
                    strategy_id=self.strategy_id,
                ),
                regime,
                "trend breakout confirmed",
            )

        if regime.regime == MarketRegime.TRENDING_DOWN and self.config.allow_short_signals:
            breakout_fraction = max(0.0, (prior_low - price) / prior_low)
            if price >= prior_low or breakout_fraction < self.config.minimum_breakout_fraction:
                return StrategyDecision(None, regime, "downtrend present but breakdown not confirmed")
            risk_distance = current_atr * self.config.stop_atr_multiple
            stop = price + risk_distance
            target = price - (risk_distance * self.config.reward_to_risk)
            if target <= 0:
                return StrategyDecision(None, regime, "invalid target after risk calculation")
            confidence = self._confidence(regime, breakout_fraction)
            return StrategyDecision(
                TradeSignal(
                    symbol=series.symbol,
                    side=TradeSide.SELL,
                    price=price,
                    stop_loss=stop,
                    take_profit=target,
                    confidence=confidence,
                    strategy_id=self.strategy_id,
                ),
                regime,
                "trend breakdown confirmed",
            )

        return StrategyDecision(None, regime, f"no momentum trade in {regime.regime.value} regime")

    @staticmethod
    def _confidence(regime: RegimeReading, breakout_fraction: float) -> float:
        regime_component = min(0.20, regime.trend_strength * 20.0)
        breakout_component = min(0.15, breakout_fraction * 15.0)
        return min(0.95, 0.60 + regime_component + breakout_component)


@dataclass(frozen=True)
class MeanReversionConfig:
    lookback: int = 20
    entry_deviation: float = 0.02
    stop_deviation: float = 0.035
    reward_to_risk: float = 1.5

    def __post_init__(self) -> None:
        if self.lookback <= 2:
            raise ValueError("lookback must be greater than two")
        if not 0 < self.entry_deviation < self.stop_deviation < 1:
            raise ValueError("deviation thresholds are invalid")
        if self.reward_to_risk <= 0:
            raise ValueError("reward_to_risk must be positive")


class MeanReversionStrategy:
    def __init__(
        self,
        config: MeanReversionConfig | None = None,
        regime_detector: RegimeDetector | None = None,
    ) -> None:
        self.config = config or MeanReversionConfig()
        self.regime_detector = regime_detector or RegimeDetector()
        self._strategy_id = "mean_reversion_v1"

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def minimum_bars(self) -> int:
        return max(self.config.lookback, self.regime_detector.minimum_bars)

    def evaluate(self, series: MarketSeries) -> StrategyDecision:
        regime = self.regime_detector.detect(series)
        if len(series.candles) < self.minimum_bars:
            return StrategyDecision(None, regime, "insufficient bars")
        if regime.regime != MarketRegime.RANGING:
            return StrategyDecision(None, regime, "mean reversion disabled outside ranging regime")

        mean = sma(series.closes, self.config.lookback)
        if mean is None:
            return StrategyDecision(None, regime, "moving average unavailable")
        price = series.last.close
        deviation = (price - mean) / mean

        if deviation <= -self.config.entry_deviation:
            stop = mean * (1.0 - self.config.stop_deviation)
            risk = price - stop
            if risk <= 0:
                return StrategyDecision(None, regime, "invalid long risk distance")
            target = price + (risk * self.config.reward_to_risk)
            confidence = min(0.90, 0.60 + abs(deviation) * 4.0)
            return StrategyDecision(
                TradeSignal(series.symbol, TradeSide.BUY, price, confidence, self.strategy_id, stop, target),
                regime,
                "range downside deviation detected",
            )

        if deviation >= self.config.entry_deviation:
            stop = mean * (1.0 + self.config.stop_deviation)
            risk = stop - price
            if risk <= 0:
                return StrategyDecision(None, regime, "invalid short risk distance")
            target = price - (risk * self.config.reward_to_risk)
            if target <= 0:
                return StrategyDecision(None, regime, "invalid short target")
            confidence = min(0.90, 0.60 + abs(deviation) * 4.0)
            return StrategyDecision(
                TradeSignal(series.symbol, TradeSide.SELL, price, confidence, self.strategy_id, stop, target),
                regime,
                "range upside deviation detected",
            )

        return StrategyDecision(None, regime, "price remains inside mean-reversion entry band")


class AdaptiveStrategyRouter:
    """Selects a baseline strategy from the detected market regime."""

    def __init__(
        self,
        momentum: AdaptiveMomentumStrategy | None = None,
        mean_reversion: MeanReversionStrategy | None = None,
        regime_detector: RegimeDetector | None = None,
    ) -> None:
        self.regime_detector = regime_detector or RegimeDetector()
        self.momentum = momentum or AdaptiveMomentumStrategy(regime_detector=self.regime_detector)
        self.mean_reversion = mean_reversion or MeanReversionStrategy(regime_detector=self.regime_detector)
        self._strategy_id = "adaptive_router_v1"

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def minimum_bars(self) -> int:
        return max(self.momentum.minimum_bars, self.mean_reversion.minimum_bars)

    def evaluate(self, series: MarketSeries) -> StrategyDecision:
        reading = self.regime_detector.detect(series)
        if reading.regime in {MarketRegime.TRENDING_UP, MarketRegime.TRENDING_DOWN}:
            return self.momentum.evaluate(series)
        if reading.regime == MarketRegime.RANGING:
            return self.mean_reversion.evaluate(series)
        return StrategyDecision(None, reading, "uncertain regime: no trade")
