from __future__ import annotations

from dataclasses import dataclass

from .indicators import atr, ema
from .market import MarketSeries
from .models import TradeSide, TradeSignal
from .regime import MarketRegime, RegimeDetector, RegimeReading
from .strategy import StrategyDecision


@dataclass(frozen=True)
class TrendPullbackConfig:
    """Research-only configuration for the predeclared pullback hypothesis."""

    fast_ema: int = 10
    atr_period: int = 14
    stop_atr_multiple: float = 1.5
    reward_to_risk: float = 2.0
    allow_short_signals: bool = True

    def __post_init__(self) -> None:
        if self.fast_ema <= 1 or self.atr_period <= 1:
            raise ValueError("indicator periods must be greater than one")
        if self.stop_atr_multiple <= 0 or self.reward_to_risk <= 0:
            raise ValueError("risk multipliers must be positive")


class TrendPullbackStrategy:
    """Research-only trend continuation candidate.

    Hypothesis: after a regime is already classified as trending, a temporary
    touch through the fast EMA followed by a directional recovery close offers a
    better-timed entry than buying or selling a fresh price breakout.

    This first candidate intentionally keeps the same 1.5 ATR stop and 2R target
    geometry used by the momentum baseline so the entry family is the material
    change under test.
    """

    def __init__(
        self,
        config: TrendPullbackConfig | None = None,
        regime_detector: RegimeDetector | None = None,
    ) -> None:
        self.config = config or TrendPullbackConfig()
        self.regime_detector = regime_detector or RegimeDetector()
        self._strategy_id = "trend_pullback_v1"

    @property
    def strategy_id(self) -> str:
        return self._strategy_id

    @property
    def minimum_bars(self) -> int:
        return max(
            self.config.fast_ema,
            self.config.atr_period + 1,
            self.regime_detector.minimum_bars,
        )

    def evaluate(self, series: MarketSeries) -> StrategyDecision:
        regime = self.regime_detector.detect(series)
        if len(series.candles) < self.minimum_bars:
            return StrategyDecision(None, regime, "insufficient bars")

        fast = ema(series.closes, self.config.fast_ema)
        current_atr = atr(series.candles, self.config.atr_period)
        if fast is None or current_atr is None:
            return StrategyDecision(None, regime, "indicator unavailable")

        bar = series.last
        price = bar.close
        signal_time = bar.utc_timestamp
        risk_distance = current_atr * self.config.stop_atr_multiple

        if regime.regime == MarketRegime.TRENDING_UP:
            touched = bar.low <= fast
            recovered = price > fast
            directional_close = price > bar.open
            if not (touched and recovered and directional_close):
                return StrategyDecision(None, regime, "uptrend present but pullback recovery not confirmed")
            stop = price - risk_distance
            target = price + (risk_distance * self.config.reward_to_risk)
            confidence = self._confidence(regime, (price - fast) / fast)
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
                "uptrend pullback recovered above fast EMA",
            )

        if regime.regime == MarketRegime.TRENDING_DOWN and self.config.allow_short_signals:
            touched = bar.high >= fast
            recovered = price < fast
            directional_close = price < bar.open
            if not (touched and recovered and directional_close):
                return StrategyDecision(None, regime, "downtrend present but pullback recovery not confirmed")
            stop = price + risk_distance
            target = price - (risk_distance * self.config.reward_to_risk)
            if target <= 0:
                return StrategyDecision(None, regime, "invalid target after risk calculation")
            confidence = self._confidence(regime, (fast - price) / fast)
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
                "downtrend pullback recovered below fast EMA",
            )

        return StrategyDecision(None, regime, f"no pullback trade in {regime.regime.value} regime")

    @staticmethod
    def _confidence(regime: RegimeReading, recovery_fraction: float) -> float:
        regime_component = min(0.20, regime.trend_strength * 20.0)
        recovery_component = min(0.10, max(0.0, recovery_fraction) * 10.0)
        return min(0.90, 0.60 + regime_component + recovery_component)
