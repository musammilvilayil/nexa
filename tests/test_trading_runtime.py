import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from skills.trading import (
    AutonomousPaperTrader,
    Candle,
    MarketSeries,
    PaperBroker,
    RegimeDetector,
    StrategyDecision,
    TradeSide,
    TradeSignal,
    TradingMandate,
    TradingMode,
)


class RuntimeStrategy:
    strategy_id = "runtime_test"
    minimum_bars = 1

    def evaluate(self, series):
        price = series.last.close
        signal = TradeSignal(
            symbol=series.symbol,
            side=TradeSide.BUY,
            price=price,
            confidence=0.9,
            strategy_id=self.strategy_id,
            stop_loss=price - 2,
            take_profit=price + 4,
        )
        return StrategyDecision(signal, RegimeDetector().detect(series), "runtime test")


def make_mandate(mode=TradingMode.PAPER_AUTONOMOUS):
    return TradingMandate(
        mode=mode,
        allowed_symbols=("NIFTY",),
        max_notional_per_trade=10_000,
        max_total_exposure=20_000,
        max_risk_per_trade=100,
        max_daily_loss=500,
        max_open_positions=1,
        min_signal_confidence=0.6,
        allowed_strategies=("runtime_test",),
    )


class AutonomousPaperRuntimeTests(unittest.TestCase):
    def test_runtime_enters_then_exits_on_stop_without_confirmation(self):
        start = datetime.now(timezone.utc) - timedelta(minutes=2)
        first = Candle(start, 100, 101, 99, 100, 1000)
        broker = PaperBroker(fee_bps=0, slippage_bps=0)
        runtime = AutonomousPaperTrader(
            make_mandate(),
            RuntimeStrategy(),
            broker=broker,
            max_market_age_seconds=3600,
        )

        entered = runtime.on_market_update(MarketSeries("NIFTY", (first,)))
        self.assertEqual(entered.status, "entered")
        self.assertGreater(broker.portfolio.position_quantity("NIFTY"), 0)

        second = Candle(start + timedelta(minutes=1), 100, 101, 97, 98, 1000)
        exited = runtime.on_market_update(MarketSeries("NIFTY", (first, second)))
        self.assertEqual(exited.status, "exit")
        self.assertEqual(exited.reason, "stop_loss")
        self.assertEqual(broker.portfolio.position_quantity("NIFTY"), 0)

    def test_runtime_processes_each_bar_only_once(self):
        stamp = datetime.now(timezone.utc)
        series = MarketSeries("NIFTY", (Candle(stamp, 100, 101, 99, 100, 1000),))
        runtime = AutonomousPaperTrader(make_mandate(), RuntimeStrategy(), max_market_age_seconds=3600)
        runtime.on_market_update(series, now=stamp)
        duplicate = runtime.on_market_update(series, now=stamp)
        self.assertEqual(duplicate.status, "noop")

    def test_runtime_is_disabled_outside_autonomous_paper_mode(self):
        stamp = datetime.now(timezone.utc)
        series = MarketSeries("NIFTY", (Candle(stamp, 100, 101, 99, 100, 1000),))
        runtime = AutonomousPaperTrader(make_mandate(TradingMode.RESEARCH), RuntimeStrategy())
        result = runtime.on_market_update(series, now=stamp)
        self.assertEqual(result.status, "disabled")
        self.assertEqual(len(runtime.broker.orders), 0)


if __name__ == "__main__":
    unittest.main()
