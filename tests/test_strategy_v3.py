import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from skills.trading.market import Candle, MarketSeries
from skills.trading.regime import MarketRegime, RegimeReading
from skills.trading.strategy_v3 import AdaptiveMomentumStrategyV3, MomentumV3Config
from skills.trading.models import TradeSide


class FixedUptrendDetector:
    minimum_bars = 1

    def detect(self, _series):
        return RegimeReading(
            MarketRegime.TRENDING_UP,
            trend_strength=0.01,
            volatility_ratio=0.02,
            reason="test uptrend",
        )


def breakout_series(*, final_close: float, final_high: float, final_low: float) -> MarketSeries:
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
            final_high,
            final_low,
            final_close,
            1000.0,
        )
    )
    return MarketSeries("NIFTY", tuple(candles))


class MomentumV3Tests(unittest.TestCase):
    def test_rejects_breakout_that_closes_mid_range(self):
        strategy = AdaptiveMomentumStrategyV3(regime_detector=FixedUptrendDetector())
        decision = strategy.evaluate(
            breakout_series(final_close=100.2, final_high=101.0, final_low=99.0)
        )
        self.assertIsNone(decision.signal)
        self.assertIn("did not close strongly enough", decision.reason)

    def test_accepts_breakout_that_closes_near_bar_high(self):
        strategy = AdaptiveMomentumStrategyV3(regime_detector=FixedUptrendDetector())
        decision = strategy.evaluate(
            breakout_series(final_close=100.9, final_high=101.0, final_low=99.0)
        )
        self.assertIsNotNone(decision.signal)
        self.assertEqual(decision.signal.side, TradeSide.BUY)
        self.assertEqual(decision.signal.strategy_id, "adaptive_momentum_v3")
        self.assertLess(decision.signal.stop_loss, decision.signal.price)
        self.assertGreater(decision.signal.take_profit, decision.signal.price)

    def test_config_rejects_close_location_below_half(self):
        with self.assertRaisesRegex(ValueError, "minimum_close_location"):
            MomentumV3Config(minimum_close_location=0.49)


if __name__ == "__main__":
    unittest.main()
