import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from skills.trading import (
    BacktestEngine,
    Candle,
    MarketSeries,
    RegimeDetector,
    StrategyDecision,
    TradeSide,
    TradeSignal,
    TradingMandate,
    TradingMode,
)


class AlwaysLong:
    strategy_id = "research_test"
    minimum_bars = 1

    def evaluate(self, series):
        price = series.last.close
        return StrategyDecision(
            TradeSignal(
                series.symbol,
                TradeSide.BUY,
                price,
                0.9,
                self.strategy_id,
                price - 5,
                price + 50,
                series.last.utc_timestamp,
            ),
            RegimeDetector().detect(series),
            "test",
        )


class ResearchBacktestModeTests(unittest.TestCase):
    def test_research_mandate_can_simulate_without_enabling_external_orders(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        series = MarketSeries(
            "NIFTY",
            (
                Candle(start, 100, 102, 99, 101, 1000),
                Candle(start + timedelta(hours=1), 102, 104, 101, 103, 1000),
                Candle(start + timedelta(hours=2), 104, 110, 103, 109, 1000),
            ),
        )
        mandate = TradingMandate(
            mode=TradingMode.RESEARCH,
            allowed_symbols=("NIFTY",),
            allowed_strategies=("research_test",),
            max_notional_per_trade=100_000,
            max_total_exposure=100_000,
            max_risk_per_trade=1_000,
            max_daily_loss=5_000,
            max_open_positions=1,
        )

        report = BacktestEngine(fee_bps=0, slippage_bps=0).run(series, AlwaysLong(), mandate)

        self.assertEqual(mandate.mode, TradingMode.RESEARCH)
        self.assertEqual(len(report.trades), 1)


if __name__ == "__main__":
    unittest.main()
