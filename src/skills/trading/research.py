from __future__ import annotations

from dataclasses import dataclass

from .backtest import BacktestEngine, BacktestReport
from .market import MarketSeries
from .metrics import PerformanceMetrics, calculate_metrics
from .models import TradingMandate
from .strategy import Strategy
from .validation import EvaluationDecision, StrategyEvaluator, WalkForwardSplitter


@dataclass(frozen=True)
class ResearchWindowResult:
    index: int
    train_bars: int
    test_bars: int
    backtest: BacktestReport
    metrics: PerformanceMetrics


@dataclass(frozen=True)
class StrategyResearchReport:
    symbol: str
    strategy_id: str
    windows: tuple[ResearchWindowResult, ...]
    evaluation: EvaluationDecision


class TradingResearchPipeline:
    """Out-of-sample research pipeline for fixed strategy candidates.

    The current pipeline does not tune parameters on the training slice. It keeps
    train/test boundaries explicit so a future optimizer can be inserted without
    leaking test data into selection.
    """

    def __init__(
        self,
        *,
        backtester: BacktestEngine | None = None,
        splitter: WalkForwardSplitter | None = None,
        evaluator: StrategyEvaluator | None = None,
    ) -> None:
        self.backtester = backtester or BacktestEngine()
        self.splitter = splitter or WalkForwardSplitter()
        self.evaluator = evaluator or StrategyEvaluator()

    def run_walk_forward(
        self,
        series: MarketSeries,
        strategy: Strategy,
        mandate: TradingMandate,
        *,
        train_bars: int,
        test_bars: int,
        step_bars: int | None = None,
        initial_equity: float = 100_000.0,
    ) -> StrategyResearchReport:
        windows = self.splitter.split(
            series,
            train_bars=train_bars,
            test_bars=test_bars,
            step_bars=step_bars,
        )
        if not windows:
            raise ValueError("series is too short for requested walk-forward windows")

        results: list[ResearchWindowResult] = []
        metrics: list[PerformanceMetrics] = []
        for index, window in enumerate(windows):
            if len(window.test.candles) < max(2, strategy.minimum_bars):
                raise ValueError(
                    "test_bars must be at least the strategy minimum bars to avoid hidden train/test warmup leakage"
                )
            report = self.backtester.run(
                window.test,
                strategy,
                mandate,
                initial_equity=initial_equity,
            )
            metric = calculate_metrics(report)
            metrics.append(metric)
            results.append(
                ResearchWindowResult(
                    index=index,
                    train_bars=len(window.train.candles),
                    test_bars=len(window.test.candles),
                    backtest=report,
                    metrics=metric,
                )
            )

        evaluation = self.evaluator.evaluate_windows(tuple(metrics))
        return StrategyResearchReport(
            symbol=series.symbol,
            strategy_id=strategy.strategy_id,
            windows=tuple(results),
            evaluation=evaluation,
        )
