import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from skills.trading import (
    AdaptiveMomentumStrategyV2,
    Candle,
    MarketRegime,
    MarketSeries,
    MomentumV2Config,
    RegimeReading,
    TradeSide,
)


class FixedUptrendDetector:
    minimum_bars = 1

    def detect(self, _series):
        return RegimeReading(
            MarketRegime.TRENDING_UP,
            trend_strength=0.01,
            volatility_ratio=0.02,
            reason="test uptrend",
        )


def breakout_series(final_close: float) -> MarketSeries:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [
        Candle(
            start + timedelta(days=index),
            99.2,
            100.0,
            98.0,
            99.5,
            1000.0,
        )
        for index in range(20)
    ]
    candles.append(
        Candle(
            start + timedelta(days=20),
            99.5,
            max(101.3, final_close),
            98.5,
            final_close,
            1000.0,
        )
    )
    return MarketSeries("NIFTY", tuple(candles))


class MomentumV2Tests(unittest.TestCase):
    def test_rejects_breakout_that_is_small_relative_to_atr(self):
        strategy = AdaptiveMomentumStrategyV2(regime_detector=FixedUptrendDetector())
        decision = strategy.evaluate(breakout_series(100.05))
        self.assertIsNone(decision.signal)
        self.assertIn("volatility-normalized breakout not confirmed", decision.reason)

    def test_accepts_breakout_that_clears_atr_filter(self):
        strategy = AdaptiveMomentumStrategyV2(regime_detector=FixedUptrendDetector())
        decision = strategy.evaluate(breakout_series(101.0))
        self.assertIsNotNone(decision.signal)
        self.assertEqual(decision.signal.side, TradeSide.BUY)
        self.assertEqual(decision.signal.strategy_id, "adaptive_momentum_v2")
        self.assertLess(decision.signal.stop_loss, decision.signal.price)
        self.assertGreater(decision.signal.take_profit, decision.signal.price)

    def test_config_rejects_negative_atr_breakout_multiple(self):
        with self.assertRaisesRegex(ValueError, "minimum_breakout_atr_multiple"):
            MomentumV2Config(minimum_breakout_atr_multiple=-0.1)


if __name__ == "__main__":
    unittest.main()
