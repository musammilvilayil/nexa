from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sandbox import SandboxRunner

from .forge import TeacherSkillForge
from .models import SkillCandidate, TrainingAttempt, TrainingNeed, TrainingPolicy, TrainingReport
from .promotion import CandidateStore, TrainingPromotionGate


class CandidateSandbox(Protocol):
    def run(self, files):
        ...


@dataclass
class TrainingBudget:
    teacher_calls: int = 0


class AutonomousTrainer:
    """Bounded teacher -> sandbox -> repair -> promotion pipeline.

    This class deliberately has no broker access and no kernel-policy mutation
    API. Generated candidates are treated as untrusted text until the sandbox
    passes. Automatic promotion is limited by TrainingPromotionGate.
    """

    def __init__(
        self,
        *,
        forge: TeacherSkillForge | None = None,
        sandbox: CandidateSandbox | None = None,
        policy: TrainingPolicy | None = None,
        promotion_gate: TrainingPromotionGate | None = None,
        store: CandidateStore | None = None,
    ) -> None:
        self.policy = policy or TrainingPolicy()
        self.forge = forge or TeacherSkillForge()
        self.sandbox = sandbox or SandboxRunner()
        self.promotion_gate = promotion_gate or TrainingPromotionGate(self.policy)
        self.store = store

    def train(self, need: TrainingNeed) -> TrainingReport:
        budget = TrainingBudget()
        attempts: list[TrainingAttempt] = []
        candidate: SkillCandidate | None = None

        for number in range(1, self.policy.max_attempts + 1):
            if budget.teacher_calls >= self.policy.max_teacher_calls:
                return TrainingReport(
                    need=need,
                    success=False,
                    candidate=candidate,
                    attempts=tuple(attempts),
                    promotion_status="not_promoted",
                    reason="teacher call budget exhausted",
                )

            if candidate is None:
                candidate = self.forge.generate(need)
            else:
                failure = attempts[-1].reason if attempts else "unknown sandbox failure"
                candidate = self.forge.repair(need, candidate, failure)
            budget.teacher_calls += 1

            result = self.sandbox.run(candidate.files)
            detail = self._sandbox_reason(result)
            attempts.append(
                TrainingAttempt(
                    number=number,
                    sandbox_passed=bool(result.passed),
                    reason=detail,
                    teacher_calls_used=budget.teacher_calls,
                )
            )

            if not result.passed:
                continue

            decision = self.promotion_gate.decide(candidate)
            if decision.allowed and decision.automatic:
                if self.store is None:
                    return TrainingReport(
                        need=need,
                        success=True,
                        candidate=candidate,
                        attempts=tuple(attempts),
                        promotion_status="validated_not_staged",
                        reason="candidate passed; no persistent candidate store configured",
                    )
                path = self.store.stage(candidate)
                return TrainingReport(
                    need=need,
                    success=True,
                    candidate=candidate,
                    attempts=tuple(attempts),
                    promotion_status="staged",
                    reason=f"validated candidate staged at {path}",
                )

            return TrainingReport(
                need=need,
                success=True,
                candidate=candidate,
                attempts=tuple(attempts),
                promotion_status="approval_required",
                reason=decision.reason,
            )

        return TrainingReport(
            need=need,
            success=False,
            candidate=candidate,
            attempts=tuple(attempts),
            promotion_status="not_promoted",
            reason="maximum training attempts exhausted",
        )

    @staticmethod
    def _sandbox_reason(result) -> str:
        base = str(getattr(result, "reason", "sandbox failed"))
        process = getattr(result, "process", None)
        if process is None:
            return base
        stderr = str(getattr(process, "stderr", "") or "").strip()
        stdout = str(getattr(process, "stdout", "") or "").strip()
        detail = stderr or stdout
        if detail:
            return f"{base}: {detail[:12000]}"
        return base
