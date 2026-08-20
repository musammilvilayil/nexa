from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import CandidateRisk, SkillCandidate, TrainingPolicy


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    automatic: bool
    reason: str


class TrainingPromotionGate:
    """Decides whether a validated candidate may be promoted automatically."""

    def __init__(self, policy: TrainingPolicy | None = None) -> None:
        self.policy = policy or TrainingPolicy()

    def decide(self, candidate: SkillCandidate) -> PromotionDecision:
        if candidate.risk == CandidateRisk.READ_ONLY:
            if self.policy.auto_promote_read_only:
                return PromotionDecision(True, True, "read-only candidate may auto-promote")
            return PromotionDecision(False, False, "read-only auto-promotion disabled")

        if candidate.risk == CandidateRisk.TRADING_RESEARCH if hasattr(CandidateRisk, "TRADING_RESEARCH") else False:
            return PromotionDecision(False, False, "unsupported risk classification")

        if candidate.risk == CandidateRisk.LIVE_TRADING:
            return PromotionDecision(False, False, "live trading requires explicit owner authorization")

        if candidate.risk in {CandidateRisk.REMOTE, CandidateRisk.DESTRUCTIVE}:
            return PromotionDecision(False, False, "remote/destructive capability requires owner approval")

        return PromotionDecision(False, False, "local mutation candidate requires approval")


class CandidateStore:
    """Persists validated candidates under a single contained staging root.

    Staging is not runtime registration. A staged candidate becomes executable
    only through a separate registry/promotion workflow.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def stage(self, candidate: SkillCandidate) -> Path:
        target = (self.root / candidate.name).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("candidate path escaped staging root")
        target.mkdir(parents=True, exist_ok=True)

        for relative_name, source in candidate.files.items():
            relative = Path(relative_name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError(f"unsafe candidate path: {relative_name}")
            destination = (target / relative).resolve()
            if not destination.is_relative_to(target):
                raise ValueError(f"candidate file escaped target: {relative_name}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(source, encoding="utf-8")
        return target
