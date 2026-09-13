import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from skills.trading import (
    Candle,
    EvaluationDecision,
    MarketRegime,
    MarketSeries,
    RegimeReading,
    RiskEngine,
    RiskSnapshot,
    StrategyDecision,
    StrategyPromotionStore,
    StrategyResearchReport,
    StrategyStage,
    TradeSide,
    TradeSignal,
    TradingBrain,
    TradingMandate,
    TradingMode,
)
from skills.trading.strategy import AdaptiveStrategyRouter


class FakeResearchPipeline:
    def __init__(self, passed: bool):
        self.passed = passed
        self.calls = []

    def run_walk_forward(self, series, strategy, mandate, **kwargs):
        self.calls.append((series.symbol, strategy.strategy_id, kwargs))
        reasons = ("promotion thresholds passed",) if self.passed else ("insufficient evidence",)
        return StrategyResearchReport(
            symbol=series.symbol,
            strategy_id=strategy.strategy_id,
            windows=(),
            evaluation=EvaluationDecision(self.passed, reasons, 1, 1 if self.passed else 0),
        )


class FakeRegimeDetector:
    minimum_bars = 1

    def detect(self, series):
        return RegimeReading(MarketRegime.TRENDING_UP, 0.02, 0.01, "test trend")


class FakeSignalStrategy:
    strategy_id = "child_strategy"
    minimum_bars = 1

    def evaluate(self, series):
        return StrategyDecision(
            TradeSignal(
                symbol=series.symbol,
                side=TradeSide.BUY,
                price=series.last.close,
                confidence=0.8,
                strategy_id=self.strategy_id,
                stop_loss=series.last.close - 1.0,
                take_profit=series.last.close + 2.0,
            ),
            RegimeReading(MarketRegime.TRENDING_UP, 0.02, 0.01, "test trend"),
            "test signal",
        )


class NoopStrategy:
    strategy_id = "adaptive_router_v1"
    minimum_bars = 2

    def evaluate(self, series):
        return StrategyDecision(
            None,
            RegimeReading(MarketRegime.UNCERTAIN, 0.0, 0.0, "noop"),
            "noop",
        )


def series(count=6):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    for index in range(count):
        price = 100.0 + index
        candles.append(
            Candle(
                timestamp=start + timedelta(minutes=index),
                open=price,
                high=price + 1.0,
                low=price - 1.0,
                close=price,
                volume=1000.0,
            )
        )
    return MarketSeries("NIFTY50", tuple(candles))


def mandate(mode=TradingMode.RESEARCH):
    return TradingMandate(
        mode=mode,
        allowed_symbols=("NIFTY50",),
        allowed_strategies=("adaptive_router_v1",),
        max_notional_per_trade=10000.0,
        max_total_exposure=25000.0,
        max_risk_per_trade=250.0,
        max_daily_loss=500.0,
        max_open_positions=3,
        min_signal_confidence=0.60,
        allow_short=False,
        require_stop_loss=True,
    )


class TradingBrainTests(unittest.TestCase):
    def test_passed_research_promotes_strategy_to_paper(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StrategyPromotionStore(Path(temp) / "strategy.db")
            pipeline = FakeResearchPipeline(True)
            brain = TradingBrain(
                mandate=mandate(),
                promotion_store=store,
                strategy=NoopStrategy(),
                research_pipeline=pipeline,
            )

            result = brain.research(series(), train_bars=3, test_bars=3)

            self.assertTrue(result.promotion.allowed)
            self.assertEqual(result.stage, StrategyStage.PAPER)
            self.assertEqual(store.stage("adaptive_router_v1"), StrategyStage.PAPER)

    def test_failed_research_cannot_promote(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StrategyPromotionStore(Path(temp) / "strategy.db")
            brain = TradingBrain(
                mandate=mandate(),
                promotion_store=store,
                strategy=NoopStrategy(),
                research_pipeline=FakeResearchPipeline(False),
            )

            result = brain.research(series(), train_bars=3, test_bars=3)

            self.assertFalse(result.promotion.allowed)
            self.assertEqual(result.stage, StrategyStage.RESEARCH)

    def test_paper_runtime_requires_paper_mode_and_promotion(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StrategyPromotionStore(Path(temp) / "strategy.db")
            brain = TradingBrain(
                mandate=mandate(TradingMode.PAPER_AUTONOMOUS),
                promotion_store=store,
                strategy=NoopStrategy(),
            )
            with self.assertRaises(PermissionError):
                brain.arm_paper_runtime()

            store.set_stage("adaptive_router_v1", StrategyStage.PAPER, ("test promotion",))
            brain.arm_paper_runtime()
            self.assertEqual(brain.on_market_update(series()).status, "no_trade")

    def test_adaptive_router_uses_stable_authorized_strategy_id(self):
        router = AdaptiveStrategyRouter(
            momentum=FakeSignalStrategy(),
            mean_reversion=FakeSignalStrategy(),
            regime_detector=FakeRegimeDetector(),
        )
        decision = router.evaluate(series(2))
        self.assertIsNotNone(decision.signal)
        self.assertEqual(decision.signal.strategy_id, "adaptive_router_v1")

    def test_risk_engine_rejects_unapproved_strategy(self):
        signal = TradeSignal(
            symbol="NIFTY50",
            side=TradeSide.BUY,
            price=100.0,
            confidence=0.9,
            strategy_id="unapproved",
            stop_loss=99.0,
            take_profit=102.0,
        )
        decision = RiskEngine().evaluate(
            signal,
            1,
            mandate(TradingMode.PAPER_AUTONOMOUS),
            RiskSnapshot(),
        )
        self.assertFalse(decision.approved)
        self.assertIn("strategy not authorized", decision.reason)


if __name__ == "__main__":
    unittest.main()
