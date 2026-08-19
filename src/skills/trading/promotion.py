from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from .research import StrategyResearchReport


class StrategyStage(str, Enum):
    RESEARCH = "research"
    PAPER = "paper"
    LIVE_ELIGIBLE = "live_eligible"
    DISABLED = "disabled"


@dataclass(frozen=True)
class PaperEvidence:
    trading_days: int
    closed_trades: int
    net_pnl: float
    max_drawdown_pct: float
    safety_violations: int = 0

    def __post_init__(self) -> None:
        if self.trading_days < 0 or self.closed_trades < 0 or self.safety_violations < 0:
            raise ValueError("paper evidence counts cannot be negative")
        if self.max_drawdown_pct < 0:
            raise ValueError("max_drawdown_pct cannot be negative")


@dataclass(frozen=True)
class PromotionPolicy:
    min_paper_days: int = 20
    min_paper_trades: int = 30
    max_paper_drawdown_pct: float = 15.0

    def __post_init__(self) -> None:
        if self.min_paper_days <= 0 or self.min_paper_trades <= 0:
            raise ValueError("paper minimums must be positive")
        if self.max_paper_drawdown_pct <= 0:
            raise ValueError("max_paper_drawdown_pct must be positive")


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    target_stage: StrategyStage
    reasons: tuple[str, ...]


class StrategyPromotionGate:
    """Separates research evidence, paper evidence, and owner authorization."""

    def __init__(self, policy: PromotionPolicy | None = None) -> None:
        self.policy = policy or PromotionPolicy()

    def research_to_paper(self, report: StrategyResearchReport) -> PromotionDecision:
        if report.evaluation.passed:
            return PromotionDecision(True, StrategyStage.PAPER, ("out-of-sample research gate passed",))
        return PromotionDecision(False, StrategyStage.PAPER, tuple(report.evaluation.reasons))

    def paper_to_live_eligible(
        self,
        research: StrategyResearchReport,
        paper: PaperEvidence,
        *,
        owner_approved: bool,
    ) -> PromotionDecision:
        reasons: list[str] = []
        if not research.evaluation.passed:
            reasons.append("research evaluation is not passed")
        if paper.trading_days < self.policy.min_paper_days:
            reasons.append("insufficient autonomous paper-trading days")
        if paper.closed_trades < self.policy.min_paper_trades:
            reasons.append("insufficient autonomous paper-trading sample")
        if paper.max_drawdown_pct > self.policy.max_paper_drawdown_pct:
            reasons.append("paper drawdown exceeds live-eligibility policy")
        if paper.safety_violations > 0:
            reasons.append("paper run contains safety violations")
        if not owner_approved:
            reasons.append("owner has not approved live eligibility")
        return PromotionDecision(
            not reasons,
            StrategyStage.LIVE_ELIGIBLE,
            tuple(reasons) if reasons else ("research, paper, and owner gates passed",),
        )


class StrategyPromotionStore:
    """SQLite strategy stage ledger. Live arming is intentionally separate."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_stage (
                    strategy_id TEXT PRIMARY KEY,
                    stage TEXT NOT NULL,
                    updated_at_utc TEXT NOT NULL,
                    reason_json TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS strategy_stage_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    changed_at_utc TEXT NOT NULL,
                    reason_json TEXT NOT NULL
                )
                """
            )

    def register(self, strategy_id: str) -> None:
        key = strategy_id.strip()
        if not key:
            raise ValueError("strategy_id required")
        if self.stage(key) is None:
            self.set_stage(key, StrategyStage.RESEARCH, ("strategy registered",))

    def set_stage(
        self,
        strategy_id: str,
        stage: StrategyStage,
        reasons: tuple[str, ...],
    ) -> None:
        key = strategy_id.strip()
        if not key or not reasons:
            raise ValueError("strategy_id and reasons are required")
        now = datetime.now(timezone.utc).isoformat()
        reason_json = json.dumps(list(reasons), separators=(",", ":"))
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO strategy_stage(strategy_id, stage, updated_at_utc, reason_json)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                    stage=excluded.stage,
                    updated_at_utc=excluded.updated_at_utc,
                    reason_json=excluded.reason_json
                """,
                (key, stage.value, now, reason_json),
            )
            connection.execute(
                """
                INSERT INTO strategy_stage_history(strategy_id, stage, changed_at_utc, reason_json)
                VALUES (?, ?, ?, ?)
                """,
                (key, stage.value, now, reason_json),
            )

    def apply_decision(self, strategy_id: str, decision: PromotionDecision) -> bool:
        if not decision.allowed:
            return False
        self.set_stage(strategy_id, decision.target_stage, decision.reasons)
        return True

    def disable(self, strategy_id: str, reason: str) -> None:
        message = reason.strip()
        if not message:
            raise ValueError("disable reason required")
        self.set_stage(strategy_id, StrategyStage.DISABLED, (message,))

    def stage(self, strategy_id: str) -> StrategyStage | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT stage FROM strategy_stage WHERE strategy_id = ?",
                (strategy_id.strip(),),
            ).fetchone()
        return None if row is None else StrategyStage(row["stage"])
