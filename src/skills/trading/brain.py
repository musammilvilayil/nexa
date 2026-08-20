from __future__ import annotations

from dataclasses import dataclass

from .market import MarketSeries, validate_market_series
from .models import TradingMandate, TradingMode
from .paper import PaperBroker
from .promotion import (
    PromotionDecision,
    StrategyPromotionGate,
    StrategyPromotionStore,
    StrategyStage,
)
from .research import StrategyResearchReport, TradingResearchPipeline
from .runtime import AutonomousPaperTrader, PaperCycleResult
from .strategy import AdaptiveStrategyRouter, Strategy


@dataclass(frozen=True)
class TradingBrainResearchResult:
    report: StrategyResearchReport
    promotion: PromotionDecision
    stage: StrategyStage


class TradingBrain:
    """High-level trading orchestration without broker-specific live execution.

    The brain connects data validation, out-of-sample research, strategy
    promotion, and autonomous paper execution. It never promotes a failed
    strategy and never turns research completion into live authorization.
    """

    def __init__(
        self,
        *,
        mandate: TradingMandate,
        promotion_store: StrategyPromotionStore,
        strategy: Strategy | None = None,
        research_pipeline: TradingResearchPipeline | None = None,
        promotion_gate: StrategyPromotionGate | None = None,
        paper_broker: PaperBroker | None = None,
        max_market_age_seconds: float | None = None,
    ) -> None:
        self.mandate = mandate
        self.strategy = strategy or AdaptiveStrategyRouter()
        self.research_pipeline = research_pipeline or TradingResearchPipeline()
        self.promotion_gate = promotion_gate or StrategyPromotionGate()
        self.promotion_store = promotion_store
        self.paper_broker = paper_broker or PaperBroker()
        self.max_market_age_seconds = max_market_age_seconds
        self.promotion_store.register(self.strategy.strategy_id)
        self._paper_trader: AutonomousPaperTrader | None = None

    @property
    def stage(self) -> StrategyStage:
        return self.promotion_store.stage(self.strategy.strategy_id) or StrategyStage.RESEARCH

    def research(
        self,
        series: MarketSeries,
        *,
        train_bars: int,
        test_bars: int,
        step_bars: int | None = None,
        initial_equity: float = 100_000.0,
    ) -> TradingBrainResearchResult:
        quality = validate_market_series(
            series,
            min_bars=train_bars + test_bars,
        )
        if not quality.valid:
            raise ValueError(f"market data rejected: {quality.reason}")

        report = self.research_pipeline.run_walk_forward(
            series,
            self.strategy,
            self.mandate,
            train_bars=train_bars,
            test_bars=test_bars,
            step_bars=step_bars,
            initial_equity=initial_equity,
        )
        decision = self.promotion_gate.research_to_paper(report)
        if decision.allowed:
            self.promotion_store.apply_decision(self.strategy.strategy_id, decision)
        return TradingBrainResearchResult(report, decision, self.stage)

    def arm_paper_runtime(self) -> None:
        if self.mandate.mode != TradingMode.PAPER_AUTONOMOUS:
            raise PermissionError("trading mandate is not PAPER_AUTONOMOUS")
        if self.stage not in {StrategyStage.PAPER, StrategyStage.LIVE_ELIGIBLE}:
            raise PermissionError("strategy has not passed the research-to-paper gate")
        self._paper_trader = AutonomousPaperTrader(
            self.mandate,
            self.strategy,
            broker=self.paper_broker,
            max_market_age_seconds=self.max_market_age_seconds,
        )

    def on_market_update(self, series: MarketSeries) -> PaperCycleResult:
        if self._paper_trader is None:
            return PaperCycleResult("disabled", "paper runtime is not armed")
        if self.stage not in {StrategyStage.PAPER, StrategyStage.LIVE_ELIGIBLE}:
            return PaperCycleResult("blocked", "strategy promotion state no longer permits paper execution")
        return self._paper_trader.on_market_update(series)

    def disable_strategy(self, reason: str) -> None:
        self.promotion_store.disable(self.strategy.strategy_id, reason)
        self._paper_trader = None
