from __future__ import annotations

import math
from dataclasses import dataclass

from .market import MarketSeries
from .metrics import PerformanceMetrics


@dataclass(frozen=True)
class WalkForwardWindow:
    train: MarketSeries
    test: MarketSeries


class WalkForwardSplitter:
    def split(
        self,
        series: MarketSeries,
        *,
        train_bars: int,
        test_bars: int,
        step_bars: int | None = None,
    ) -> tuple[WalkForwardWindow, ...]:
        if train_bars <= 0 or test_bars <= 0:
            raise ValueError("train_bars and test_bars must be positive")
        step = test_bars if step_bars is None else step_bars
        if step <= 0:
            raise ValueError("step_bars must be positive")

        windows: list[WalkForwardWindow] = []
        start = 0
        while start + train_bars + test_bars <= len(series.candles):
            train = MarketSeries(series.symbol, series.candles[start : start + train_bars])
            test_start = start + train_bars
            test = MarketSeries(series.symbol, series.candles[test_start : test_start + test_bars])
            windows.append(WalkForwardWindow(train, test))
            start += step
        return tuple(windows)


@dataclass(frozen=True)
class EvaluationThresholds:
    min_trades: int = 20
    min_profit_factor: float = 1.10
    min_expectancy: float = 0.0
    max_drawdown_pct: float = 15.0
    min_positive_windows_fraction: float = 0.60

    def __post_init__(self) -> None:
        if self.min_trades < 1:
            raise ValueError("min_trades must be positive")
        if self.min_profit_factor < 0:
            raise ValueError("min_profit_factor cannot be negative")
        if self.max_drawdown_pct <= 0:
            raise ValueError("max_drawdown_pct must be positive")
        if not 0.0 <= self.min_positive_windows_fraction <= 1.0:
            raise ValueError("min_positive_windows_fraction must be between 0 and 1")


@dataclass(frozen=True)
class EvaluationDecision:
    passed: bool
    reasons: tuple[str, ...]
    windows: int
    positive_windows: int


class StrategyEvaluator:
    """Promotion gate for out-of-sample paper research results.

    This gate does not claim future profitability. It only rejects candidates
    that fail minimum empirical robustness rules defined by the owner/system.
    """

    def __init__(self, thresholds: EvaluationThresholds | None = None) -> None:
        self.thresholds = thresholds or EvaluationThresholds()

    def evaluate(self, metrics: PerformanceMetrics) -> EvaluationDecision:
        return self.evaluate_windows((metrics,))

    def evaluate_windows(self, metrics: tuple[PerformanceMetrics, ...]) -> EvaluationDecision:
        if not metrics:
            return EvaluationDecision(False, ("no evaluation windows",), 0, 0)

        total_trades = sum(item.trades for item in metrics)
        positive_windows = sum(1 for item in metrics if item.net_pnl > 0)
        positive_fraction = positive_windows / len(metrics)
        worst_drawdown = max(item.max_drawdown_pct for item in metrics)
        weighted_expectancy = (
            sum(item.expectancy * item.trades for item in metrics) / total_trades
            if total_trades
            else 0.0
        )
        aggregate_profit_factor = self._aggregate_profit_factor(metrics, total_trades)

        reasons: list[str] = []
        t = self.thresholds
        if total_trades < t.min_trades:
            reasons.append(f"insufficient trades: {total_trades} < {t.min_trades}")
        if aggregate_profit_factor < t.min_profit_factor:
            reasons.append("aggregate profit factor below threshold")
        if weighted_expectancy <= t.min_expectancy:
            reasons.append("expectancy does not clear threshold")
        if worst_drawdown > t.max_drawdown_pct:
            reasons.append("max drawdown exceeds threshold")
        if positive_fraction < t.min_positive_windows_fraction:
            reasons.append("too few positive out-of-sample windows")

        return EvaluationDecision(
            passed=not reasons,
            reasons=tuple(reasons) if reasons else ("promotion thresholds passed",),
            windows=len(metrics),
            positive_windows=positive_windows,
        )

    @staticmethod
    def _aggregate_profit_factor(
        metrics: tuple[PerformanceMetrics, ...],
        total_trades: int,
    ) -> float:
        gross_profit = sum(item.gross_profit for item in metrics)
        gross_loss = sum(item.gross_loss for item in metrics)
        if gross_profit > 0 or gross_loss > 0:
            if gross_loss == 0:
                return math.inf if gross_profit > 0 else 0.0
            return gross_profit / gross_loss

        # Backward-compatible path for hand-constructed metrics that predate the
        # explicit gross-profit/gross-loss fields used by real backtest output.
        if total_trades <= 0:
            return 0.0
        if all(math.isinf(item.profit_factor) for item in metrics if item.trades > 0):
            return math.inf
        weighted = 0.0
        weight = 0
        for item in metrics:
            if item.trades <= 0:
                continue
            factor = item.profit_factor
            if math.isinf(factor):
                factor = max(10.0, StrategyEvaluator._finite_profit_factor_cap(metrics))
            weighted += factor * item.trades
            weight += item.trades
        return weighted / weight if weight else 0.0

    @staticmethod
    def _finite_profit_factor_cap(metrics: tuple[PerformanceMetrics, ...]) -> float:
        finite = [item.profit_factor for item in metrics if math.isfinite(item.profit_factor)]
        return max(finite, default=10.0)
