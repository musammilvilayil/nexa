from __future__ import annotations

from dataclasses import dataclass

from .indicators import atr, highest, lowest
from .market import MarketSeries
from .models import TradeSide, TradeSignal
from .regime import MarketRegime, RegimeDetector, RegimeReading
from .strategy import StrategyDecision


@dataclass(frozen=True)
class MomentumV3Config:
    """Research-only momentum candidate with breakout-bar close confirmation."""

    breakout_lookback: int = 20
    atr_period: int = 14
    stop_atr_multiple: float = 1.5
    reward_to_risk: float = 2.0
    minimum_breakout_fraction: float = 0.0005
    minimum_close_location: float = 0.70
    allow_short_signals: bool = True

    def __post_init__(self) -> None:
        if self.breakout_lookback <= 1 or self.atr_period <= 1:
            raise ValueError("lookback periods must be greater than one")
        if self.stop_atr_multiple <= 0 or self.reward_to_risk <= 0:
            raise ValueError("risk multipliers must be positive")
        if self.minimum_breakout_fraction < 0:
            raise ValueError("minimum_breakout_fraction cannot be negative")
        if not 0.5 <= self.minimum_close_location <= 1.0:
            raise ValueError("minimum_close_location must be between 0.5 and 1.0")


class AdaptiveMomentumStrategyV3:
    """Research-only breakout candidate that asks the signal bar to close strongly.

    V1 admits any close that clears the breakout level by a small fixed fraction.
    V2's ATR-distance filter reduced trade count without improving OOS robustness.
    V3 therefore keeps V1's breakout threshold and tests a different hypothesis:
    genuine breakouts should close near the directional edge of the signal bar.
    """

    def __init__(
        self,
        config: MomentumV3Config | None = None,
        regime_detector: RegimeDetector | None = None,
    ) -> None:
        self.config = config or MomentumV3Config()
        self.regime_detector = regime_detector or RegimeDetector()
        self._strategy_id = "adaptive_momentum_v3"

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

        bar = series.last
        price = bar.close
        signal_time = bar.utc_timestamp
        close_location = self._close_location(bar.high, bar.low, bar.close)
        if close_location is None:
            return StrategyDecision(None, regime, "signal bar has no usable range")

        if regime.regime == MarketRegime.TRENDING_UP:
            breakout_fraction = max(0.0, (price - prior_high) / prior_high)
            if price <= prior_high or breakout_fraction < self.config.minimum_breakout_fraction:
                return StrategyDecision(None, regime, "uptrend present but breakout not confirmed")
            if close_location < self.config.minimum_close_location:
                return StrategyDecision(None, regime, "breakout bar did not close strongly enough")
            risk_distance = current_atr * self.config.stop_atr_multiple
            stop = price - risk_distance
            target = price + (risk_distance * self.config.reward_to_risk)
            confidence = self._confidence(regime, breakout_fraction, close_location)
            return StrategyDecision(
                TradeSignal(
                    symbol=series.symbol,
                    side=TradeSide.BUY,
                    price=price,
                    stop_loss=stop,
                    take_profit=target,
                    confidence=confidence,
                    strategy_id=self.strategy_id,
                    generated_at_utc=signal_time,
                ),
                regime,
                "trend breakout with strong close confirmed",
            )

        if regime.regime == MarketRegime.TRENDING_DOWN and self.config.allow_short_signals:
            breakout_fraction = max(0.0, (prior_low - price) / prior_low)
            if price >= prior_low or breakout_fraction < self.config.minimum_breakout_fraction:
                return StrategyDecision(None, regime, "downtrend present but breakdown not confirmed")
            if close_location > 1.0 - self.config.minimum_close_location:
                return StrategyDecision(None, regime, "breakdown bar did not close strongly enough")
            risk_distance = current_atr * self.config.stop_atr_multiple
            stop = price + risk_distance
            target = price - (risk_distance * self.config.reward_to_risk)
            if target <= 0:
                return StrategyDecision(None, regime, "invalid target after risk calculation")
            confidence = self._confidence(regime, breakout_fraction, 1.0 - close_location)
            return StrategyDecision(
                TradeSignal(
                    symbol=series.symbol,
                    side=TradeSide.SELL,
                    price=price,
                    stop_loss=stop,
                    take_profit=target,
                    confidence=confidence,
                    strategy_id=self.strategy_id,
                    generated_at_utc=signal_time,
                ),
                regime,
                "trend breakdown with strong close confirmed",
            )

        return StrategyDecision(None, regime, f"no momentum trade in {regime.regime.value} regime")

    @staticmethod
    def _close_location(high: float, low: float, close: float) -> float | None:
        span = high - low
        if span <= 0:
            return None
        return min(1.0, max(0.0, (close - low) / span))

    @staticmethod
    def _confidence(regime: RegimeReading, breakout_fraction: float, directional_close: float) -> float:
        regime_component = min(0.20, regime.trend_strength * 20.0)
        breakout_component = min(0.10, breakout_fraction * 10.0)
        close_component = min(0.05, max(0.0, directional_close - 0.5) * 0.10)
        return min(0.95, 0.60 + regime_component + breakout_component + close_component)
