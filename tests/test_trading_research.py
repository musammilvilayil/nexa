import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from skills.trading import (
    AdaptiveMomentumStrategy,
    BacktestEngine,
    Candle,
    EvaluationThresholds,
    FixedRiskSizer,
    MarketRegime,
    MarketSeries,
    PaperPortfolio,
    PerformanceMetrics,
    RegimeDetector,
    RiskEngine,
    RiskSnapshot,
    StrategyDecision,
    StrategyEvaluator,
    TradeSide,
    TradeSignal,
    TradingJournal,
    TradingMandate,
    TradingMode,
    WalkForwardSplitter,
    validate_market_series,
)


def rising_series(count=60, symbol="NIFTY"):
    candles = []
    price = 100.0
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index in range(count):
        open_price = price
        close = open_price * 1.01
        candles.append(
            Candle(
                start + timedelta(hours=index),
                open_price,
                close * 1.002,
                open_price * 0.998,
                close,
                1000.0 + index,
            )
        )
        price = close
    return MarketSeries(symbol, tuple(candles))


def mandate(**overrides):
    values = {
        "mode": TradingMode.PAPER_AUTONOMOUS,
        "allowed_symbols": ("NIFTY",),
        "max_notional_per_trade": 100_000.0,
        "max_total_exposure": 250_000.0,
        "max_risk_per_trade": 2_000.0,
        "max_daily_loss": 5_000.0,
        "max_open_positions": 5,
        "min_signal_confidence": 0.55,
        "allow_short": False,
        "require_stop_loss": True,
    }
    values.update(overrides)
    return TradingMandate(**values)


class AlwaysLongStrategy:
    strategy_id = "always_long_test"
    minimum_bars = 1

    def evaluate(self, series):
        price = series.last.close
        signal = TradeSignal(
            series.symbol,
            TradeSide.BUY,
            price,
            0.90,
            self.strategy_id,
            price - 10.0,
            price + 100.0,
        )
        reading = RegimeDetector().detect(series)
        return StrategyDecision(signal, reading, "test signal")


class TradingResearchTests(unittest.TestCase):
    def test_market_series_rejects_duplicate_timestamps(self):
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        candle = Candle(stamp, 100, 101, 99, 100.5, 10)
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            MarketSeries("NIFTY", (candle, candle))

    def test_data_quality_can_block_stale_market_data(self):
        series = rising_series(5)
        report = validate_market_series(
            series,
            now=series.last.utc_timestamp + timedelta(hours=5),
            max_age_seconds=60,
        )
        self.assertFalse(report.valid)
        self.assertTrue(report.stale)

    def test_regime_detector_recognizes_strong_uptrend(self):
        reading = RegimeDetector().detect(rising_series())
        self.assertEqual(reading.regime, MarketRegime.TRENDING_UP)

    def test_adaptive_momentum_generates_breakout_signal(self):
        decision = AdaptiveMomentumStrategy().evaluate(rising_series())
        self.assertIsNotNone(decision.signal)
        self.assertEqual(decision.signal.side, TradeSide.BUY)
        self.assertLess(decision.signal.stop_loss, decision.signal.price)
        self.assertGreater(decision.signal.take_profit, decision.signal.price)

    def test_fixed_risk_sizer_never_rounds_above_limits(self):
        signal = TradeSignal("NIFTY", TradeSide.BUY, 100, 0.9, "x", 98, 104)
        quantity = FixedRiskSizer().size(signal, mandate(), RiskSnapshot())
        self.assertEqual(quantity, 1000)

    def test_risk_reducing_exit_remains_available_after_loss_ceiling(self):
        exit_signal = TradeSignal("NIFTY", TradeSide.SELL, 100, 0.0, "exit")
        strict = mandate(
            allowed_symbols=("RELIANCE",),
            allowed_strategies=("approved_only",),
            max_daily_loss=500.0,
        )
        snapshot = RiskSnapshot(
            total_exposure=1000,
            realized_pnl_today=-500,
            open_positions=1,
            open_symbols=("NIFTY",),
            position_quantities=(("NIFTY", 10),),
        )
        decision = RiskEngine().evaluate(exit_signal, 10, strict, snapshot)
        self.assertTrue(decision.approved)
        self.assertIn("risk-reducing", decision.reason)

    def test_portfolio_realizes_long_profit_and_fees(self):
        portfolio = PaperPortfolio()
        portfolio.apply_fill("NIFTY", TradeSide.BUY, 10, 100, 1)
        effect = portfolio.apply_fill("NIFTY", TradeSide.SELL, 10, 110, 1)
        self.assertAlmostEqual(effect.realized_pnl, 99.0)
        self.assertAlmostEqual(portfolio.realized_pnl_total, 98.0)
        self.assertEqual(portfolio.position_quantity("NIFTY"), 0)

    def test_backtest_executes_signal_on_next_bar_open(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        series = MarketSeries(
            "NIFTY",
            (
                Candle(start, 100, 102, 99, 100, 1000),
                Candle(start + timedelta(hours=1), 110, 112, 109, 111, 1000),
                Candle(start + timedelta(hours=2), 115, 121, 114, 120, 1000),
            ),
        )
        report = BacktestEngine(fee_bps=0, slippage_bps=0).run(
            series,
            AlwaysLongStrategy(),
            mandate(max_risk_per_trade=1000, max_notional_per_trade=100_000),
        )
        self.assertEqual(len(report.trades), 1)
        self.assertEqual(report.trades[0].entry_price, 110)
        self.assertEqual(report.trades[0].exit_reason, "end_of_data")

    def test_walk_forward_splitter_never_overlaps_train_and_test_inside_window(self):
        series = rising_series(50)
        windows = WalkForwardSplitter().split(series, train_bars=20, test_bars=10)
        self.assertEqual(len(windows), 3)
        for window in windows:
            self.assertLess(window.train.last.utc_timestamp, window.test.candles[0].utc_timestamp)

    def test_evaluator_rejects_weak_candidate(self):
        metrics = PerformanceMetrics(
            trades=5,
            winners=2,
            losers=3,
            net_pnl=-100,
            return_pct=-1,
            win_rate=0.4,
            expectancy=-20,
            profit_factor=0.8,
            max_drawdown=500,
            max_drawdown_pct=20,
            sharpe_like=-0.2,
        )
        evaluator = StrategyEvaluator(EvaluationThresholds(min_trades=10))
        decision = evaluator.evaluate(metrics)
        self.assertFalse(decision.passed)
        self.assertGreater(len(decision.reasons), 0)

    def test_trading_journal_persists_structured_event(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = TradingJournal(Path(temp) / "journal.db")
            event_id = journal.record(
                "paper_order",
                "filled",
                {"price": 100.0},
                symbol="nifty",
                strategy_id="test",
            )
            rows = journal.recent()
            self.assertEqual(rows[0]["id"], event_id)
            self.assertEqual(rows[0]["symbol"], "NIFTY")
            self.assertEqual(rows[0]["payload"]["price"], 100.0)


if __name__ == "__main__":
    unittest.main()
