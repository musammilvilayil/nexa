from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CurriculumModule:
    module_id: str
    title: str
    objective: str
    topics: tuple[str, ...]
    safety_focus: str
    minimum_score: float = 0.80

    def __post_init__(self) -> None:
        if not self.module_id.strip() or not self.title.strip() or not self.objective.strip():
            raise ValueError("curriculum identifiers and text are required")
        if not self.topics:
            raise ValueError("curriculum module requires topics")
        if not 0.0 < self.minimum_score <= 1.0:
            raise ValueError("minimum_score must be between 0 and 1")


class TradingCurriculum:
    """Trading-first curriculum ordered from data integrity to live safety."""

    def __init__(self, modules: tuple[CurriculumModule, ...] | None = None) -> None:
        self.modules = modules or self.default_modules()
        ids = [module.module_id for module in self.modules]
        if len(ids) != len(set(ids)):
            raise ValueError("curriculum module ids must be unique")

    def get(self, module_id: str) -> CurriculumModule:
        for module in self.modules:
            if module.module_id == module_id:
                return module
        raise KeyError(f"unknown curriculum module: {module_id}")

    @staticmethod
    def default_modules() -> tuple[CurriculumModule, ...]:
        return (
            CurriculumModule(
                "market_data_integrity",
                "Market Data Integrity",
                "Validate timestamps, OHLCV consistency, staleness, sessions, and corporate-action assumptions before research.",
                (
                    "timezone-aware timestamps",
                    "missing and duplicate bars",
                    "stale quotes",
                    "adjusted versus raw prices",
                    "survivorship bias",
                ),
                "No strategy may trade from invalid or stale data.",
            ),
            CurriculumModule(
                "execution_mechanics",
                "Execution Mechanics",
                "Understand order lifecycle, spread, slippage, fees, partial fills, and why backtests must model execution realistically.",
                (
                    "market and limit orders",
                    "bid-ask spread",
                    "slippage",
                    "fees and taxes",
                    "next-bar execution",
                ),
                "Research must never assume free or impossible fills.",
            ),
            CurriculumModule(
                "risk_position_sizing",
                "Risk and Position Sizing",
                "Size positions from predefined risk budgets instead of desired profit.",
                (
                    "risk per unit",
                    "maximum notional",
                    "portfolio exposure",
                    "daily loss ceiling",
                    "risk-reducing exits",
                ),
                "RiskEngine has final authority over every executable trade.",
            ),
            CurriculumModule(
                "probability_statistics",
                "Probability and Trading Statistics",
                "Reason about expectancy, variance, uncertainty, sample size, and the difference between win rate and edge.",
                (
                    "expectancy",
                    "variance",
                    "base rates",
                    "confidence intervals",
                    "multiple testing",
                ),
                "High win rate alone is never treated as proof of profitability.",
            ),
            CurriculumModule(
                "market_regimes",
                "Market Regimes",
                "Classify trend, range, volatility shock, and uncertainty so strategies can abstain outside their domain.",
                (
                    "trend strength",
                    "volatility normalization",
                    "range detection",
                    "regime transition",
                    "no-trade state",
                ),
                "Uncertain regimes default to no new trade.",
            ),
            CurriculumModule(
                "momentum_breakouts",
                "Momentum and Breakouts",
                "Build and critique trend-following breakout hypotheses without assuming historical success will persist.",
                (
                    "breakout confirmation",
                    "ATR stops",
                    "reward-to-risk",
                    "liquidity",
                    "false breakouts",
                ),
                "Momentum candidates require regime and execution filters.",
            ),
            CurriculumModule(
                "mean_reversion",
                "Mean Reversion",
                "Study range-bound reversion hypotheses and conditions where they fail catastrophically.",
                (
                    "deviation from mean",
                    "range regime",
                    "trend failure mode",
                    "stop placement",
                    "short-side constraints",
                ),
                "Mean reversion is disabled outside a validated ranging regime.",
            ),
            CurriculumModule(
                "backtesting_biases",
                "Backtesting Biases",
                "Detect look-ahead, leakage, survivorship, same-bar fill assumptions, and overfit parameter searches.",
                (
                    "look-ahead bias",
                    "data leakage",
                    "same-bar ambiguity",
                    "selection bias",
                    "overfitting",
                ),
                "A backtest is evidence only when its information boundary is realistic.",
            ),
            CurriculumModule(
                "walk_forward_robustness",
                "Walk-Forward Robustness",
                "Evaluate strategies on unseen windows and reject fragile parameter sets.",
                (
                    "train-test separation",
                    "walk-forward windows",
                    "drawdown stability",
                    "profit factor stability",
                    "Monte Carlo concepts",
                ),
                "Promotion uses out-of-sample evidence, not best in-sample results.",
            ),
            CurriculumModule(
                "paper_execution",
                "Autonomous Paper Execution",
                "Operate signals, sizing, stops, targets, journaling, and recovery in a simulated account.",
                (
                    "paper portfolio",
                    "duplicate-bar prevention",
                    "protective exits",
                    "audit journal",
                    "kill conditions",
                ),
                "Paper autonomy stays inside the owner mandate without per-trade confirmation.",
            ),
            CurriculumModule(
                "live_safety_kill_switches",
                "Live Safety and Kill Switches",
                "Define the controls required before any future live broker adapter can be armed.",
                (
                    "owner mandate",
                    "broker health",
                    "stale-data halt",
                    "daily loss halt",
                    "manual kill switch",
                    "strategy promotion state",
                ),
                "Training completion never auto-enables live trading.",
                minimum_score=0.90,
            ),
        )
