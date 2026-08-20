from __future__ import annotations

import math
from dataclasses import dataclass

from .backtest import BacktestReport


@dataclass(frozen=True)
class PerformanceMetrics:
    trades: int
    winners: int
    losers: int
    net_pnl: float
    return_pct: float
    win_rate: float
    expectancy: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_like: float
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    sortino_like: float = 0.0


def calculate_metrics(report: BacktestReport) -> PerformanceMetrics:
    pnls = [trade.net_pnl for trade in report.trades]
    winners = [pnl for pnl in pnls if pnl > 0]
    losers = [pnl for pnl in pnls if pnl < 0]
    net_pnl = sum(pnls)
    count = len(pnls)
    win_rate = (len(winners) / count) if count else 0.0
    expectancy = (net_pnl / count) if count else 0.0

    gross_profit = sum(winners)
    gross_loss = abs(sum(losers))
    if gross_loss == 0:
        profit_factor = math.inf if gross_profit > 0 else 0.0
    else:
        profit_factor = gross_profit / gross_loss

    max_drawdown, max_drawdown_pct = _drawdown(report)
    sharpe_like = _trade_sharpe(pnls)
    sortino_like = _trade_sortino(pnls)
    return_pct = ((report.final_equity / report.initial_equity) - 1.0) * 100.0

    return PerformanceMetrics(
        trades=count,
        winners=len(winners),
        losers=len(losers),
        net_pnl=net_pnl,
        return_pct=return_pct,
        win_rate=win_rate,
        expectancy=expectancy,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_like=sharpe_like,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        sortino_like=sortino_like,
    )


def _drawdown(report: BacktestReport) -> tuple[float, float]:
    peak = report.initial_equity
    max_drawdown = 0.0
    max_drawdown_pct = 0.0
    for point in report.equity_curve:
        peak = max(peak, point.equity)
        drawdown = max(0.0, peak - point.equity)
        pct = (drawdown / peak) * 100.0 if peak > 0 else 0.0
        max_drawdown = max(max_drawdown, drawdown)
        max_drawdown_pct = max(max_drawdown_pct, pct)
    return max_drawdown, max_drawdown_pct


def _trade_sharpe(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    variance = sum((value - mean) ** 2 for value in pnls) / (len(pnls) - 1)
    if variance <= 0:
        return 0.0
    return mean / math.sqrt(variance)


def _trade_sortino(pnls: list[float]) -> float:
    if len(pnls) < 2:
        return 0.0
    mean = sum(pnls) / len(pnls)
    downside = [min(0.0, value) for value in pnls]
    downside_variance = sum(value * value for value in downside) / len(pnls)
    if downside_variance <= 0:
        return math.inf if mean > 0 else 0.0
    return mean / math.sqrt(downside_variance)
