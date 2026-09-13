import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from skills.trading import Candle, MarketRegime, MarketSeries, RegimeReading, TradeSide
from skills.trading.trend_pullback import TrendPullbackConfig, TrendPullbackStrategy


class FixedTrendDetector:
    minimum_bars = 1

    def __init__(self, regime):
        self.regime = regime

    def detect(self, _series):
        return RegimeReading(
            self.regime,
            trend_strength=0.01,
            volatility_ratio=0.02,
            reason="test trend",
        )


def series_with_final_bar(*, open_price, high, low, close):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    for index in range(30):
        candles.append(
            Candle(
                start + timedelta(days=index),
                100.0,
                101.0,
                99.0,
                100.0,
                1000.0,
            )
        )
    candles.append(
        Candle(
            start + timedelta(days=30),
            open_price,
            high,
            low,
            close,
            1000.0,
        )
    )
    return MarketSeries("NIFTY", tuple(candles))


class TrendPullbackTests(unittest.TestCase):
    def test_uptrend_touch_and_recovery_generates_long(self):
        strategy = TrendPullbackStrategy(regime_detector=FixedTrendDetector(MarketRegime.TRENDING_UP))
        decision = strategy.evaluate(
            series_with_final_bar(open_price=99.5, high=101.0, low=99.0, close=100.5)
        )
        self.assertIsNotNone(decision.signal)
        self.assertEqual(decision.signal.side, TradeSide.BUY)
        self.assertEqual(decision.signal.strategy_id, "trend_pullback_v1")
        self.assertLess(decision.signal.stop_loss, decision.signal.price)
        self.assertGreater(decision.signal.take_profit, decision.signal.price)

    def test_uptrend_without_recovery_is_rejected(self):
        strategy = TrendPullbackStrategy(regime_detector=FixedTrendDetector(MarketRegime.TRENDING_UP))
        decision = strategy.evaluate(
            series_with_final_bar(open_price=100.2, high=100.4, low=99.0, close=99.6)
        )
        self.assertIsNone(decision.signal)
        self.assertIn("pullback recovery not confirmed", decision.reason)

    def test_downtrend_touch_and_recovery_generates_short(self):
        strategy = TrendPullbackStrategy(regime_detector=FixedTrendDetector(MarketRegime.TRENDING_DOWN))
        decision = strategy.evaluate(
            series_with_final_bar(open_price=100.5, high=101.0, low=99.0, close=99.5)
        )
        self.assertIsNotNone(decision.signal)
        self.assertEqual(decision.signal.side, TradeSide.SELL)

    def test_config_rejects_invalid_risk_geometry(self):
        with self.assertRaisesRegex(ValueError, "risk multipliers"):
            TrendPullbackConfig(stop_atr_multiple=0)


if __name__ == "__main__":
    unittest.main()
