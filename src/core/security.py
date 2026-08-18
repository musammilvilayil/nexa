from __future__ import annotations

from .contracts import PolicyDecision, PolicyOutcome, RiskTier


class SecurityGate:
    """Kernel-level risk policy independent of any specific capability."""

    def decide(self, risk: RiskTier, *, confirmed: bool = False) -> PolicyDecision:
        if risk in {RiskTier.READ, RiskTier.MUTATE}:
            return PolicyDecision(PolicyOutcome.ALLOW)

        if risk in {RiskTier.REMOTE, RiskTier.DESTRUCTIVE}:
            if confirmed:
                return PolicyDecision(PolicyOutcome.ALLOW, "User confirmed pending action")
            return PolicyDecision(
                PolicyOutcome.REQUIRE_CONFIRMATION,
                f"{risk.value} operation requires explicit confirmation",
            )

        return PolicyDecision(PolicyOutcome.DENY, "Unknown risk tier")
