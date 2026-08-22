from __future__ import annotations

from dataclasses import dataclass

from .indicators import atr, highest, lowest
from .market import MarketSeries
from .models import TradeSide, TradeSignal
from .regime import MarketRegime, RegimeDetector, RegimeReading
from .strategy import StrategyDecision


@dataclass(frozen=True)
class MomentumV2Config:
    """Research-only momentum candidate with volatility-normalized breakout confirmation."""

    breakout_lookback: int = 20
    atr_period: int = 14
    stop_atr_multiple: float = 1.5
    reward_to_risk: float = 2.0
    minimum_breakout_fraction: float = 0.0005
    minimum_breakout_atr_multiple: float = 0.25
    allow_short_signals: bool = True

    def __post_init__(self) -> None:
        if self.breakout_lookback <= 1 or self.atr_period <= 1:
            raise ValueError("lookback periods must be greater than one")
        if self.stop_atr_multiple <= 0 or self.reward_to_risk <= 0:
            raise ValueError("risk multipliers must be positive")
        if self.minimum_breakout_fraction < 0:
            raise ValueError("minimum_breakout_fraction cannot be negative")
        if self.minimum_breakout_atr_multiple < 0:
            raise ValueError("minimum_breakout_atr_multiple cannot be negative")


class AdaptiveMomentumStrategyV2:
    """Research-only momentum candidate that rejects weak ATR-relative breakouts.

    The v1 baseline only requires a small fixed percentage clearance above or
    below the breakout level. This candidate keeps that floor but also requires
    the breakout distance to clear a fraction of current ATR, so the entry filter
    scales with prevailing volatility instead of price alone.
    """

    def __init__(
        self,
        config: MomentumV2Config | None = None,
        regime_detector: RegimeDetector | None = None,
    ) -> None:
        self.config = config or MomentumV2Config()
        self.regime_detector = regime_detector or RegimeDetector()
        self._strategy_id = "adaptive_momentum_v2"

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
        signal_time = series.last.utc_timestamp

        if regime.regime == MarketRegime.TRENDING_UP:
            breakout_distance = price - prior_high
            required_distance = self._required_breakout_distance(prior_high, current_atr)
            if breakout_distance <= 0 or breakout_distance < required_distance:
                return StrategyDecision(None, regime, "uptrend present but volatility-normalized breakout not confirmed")
            risk_distance = current_atr * self.config.stop_atr_multiple
            stop = price - risk_distance
            target = price + (risk_distance * self.config.reward_to_risk)
            breakout_fraction = breakout_distance / prior_high
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
                    generated_at_utc=signal_time,
                ),
                regime,
                "volatility-normalized trend breakout confirmed",
            )

        if regime.regime == MarketRegime.TRENDING_DOWN and self.config.allow_short_signals:
            breakout_distance = prior_low - price
            required_distance = self._required_breakout_distance(prior_low, current_atr)
            if breakout_distance <= 0 or breakout_distance < required_distance:
                return StrategyDecision(None, regime, "downtrend present but volatility-normalized breakdown not confirmed")
            risk_distance = current_atr * self.config.stop_atr_multiple
            stop = price + risk_distance
            target = price - (risk_distance * self.config.reward_to_risk)
            if target <= 0:
                return StrategyDecision(None, regime, "invalid target after risk calculation")
            breakout_fraction = breakout_distance / prior_low
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
                    generated_at_utc=signal_time,
                ),
                regime,
                "volatility-normalized trend breakdown confirmed",
            )

        return StrategyDecision(None, regime, f"no momentum trade in {regime.regime.value} regime")

    def _required_breakout_distance(self, reference_price: float, current_atr: float) -> float:
        fixed_floor = reference_price * self.config.minimum_breakout_fraction
        volatility_floor = current_atr * self.config.minimum_breakout_atr_multiple
        return max(fixed_floor, volatility_floor)

    @staticmethod
    def _confidence(regime: RegimeReading, breakout_fraction: float) -> float:
        regime_component = min(0.20, regime.trend_strength * 20.0)
        breakout_component = min(0.15, breakout_fraction * 15.0)
        return min(0.95, 0.60 + regime_component + breakout_component)
