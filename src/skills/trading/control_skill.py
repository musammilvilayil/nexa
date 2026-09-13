from __future__ import annotations

import re
from typing import Any, Mapping

from core import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata

from .live import LiveArmController, LiveExecutionController, TradingKillSwitch
from .models import TradingMandate, TradingMode
from .promotion import StrategyPromotionStore, StrategyStage


class TradingControlSkill:
    """Owner-facing control plane for live trading state.

    Normal live orders are not routed through this text skill. It only manages
    the safety envelope: inspect state, activate/disarm safety immediately, and
    confirmation-gated clearing/arming operations. Live strategy eligibility is
    checked both when an arm request is validated and again at execution time.

    Dynamic safety state is read directly from its owning objects rather than
    copied into ContextBus, avoiding stale arm/kill/promotion flags.
    """

    def __init__(
        self,
        *,
        mandate: TradingMandate,
        promotion_store: StrategyPromotionStore,
        live_arm: LiveArmController,
        kill_switch: TradingKillSwitch,
        live_controller: LiveExecutionController | None = None,
    ) -> None:
        self.mandate = mandate
        self.promotion_store = promotion_store
        self.live_arm = live_arm
        self.kill_switch = kill_switch
        self.live_controller = live_controller
        self.metadata = SkillMetadata(
            name="trading_control",
            version="0.3.0",
            description="Owner control plane for live arming, disarming, and kill-switch state",
            operations=(
                OperationSpec("status", "Inspect live trading control state", RiskTier.READ),
                OperationSpec("activate_kill", "Activate the live trading kill switch", RiskTier.MUTATE),
                OperationSpec("disarm_live", "Immediately disarm live autonomous execution", RiskTier.MUTATE),
                OperationSpec("clear_kill", "Clear the trading kill switch", RiskTier.DESTRUCTIVE),
                OperationSpec("arm_live", "Arm a validated live-autonomous mandate", RiskTier.REMOTE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = " ".join(text.strip().split())
        lowered = normalized.lower()
        if lowered in {"/live status", "live trading status", "trading control status"}:
            return SkillMatch("trading_control", "status")
        if lowered in {"/live disarm", "disarm live trading", "live trading disarm"}:
            return SkillMatch("trading_control", "disarm_live")
        if lowered in {"/live clear-kill", "clear trading kill switch"}:
            return SkillMatch("trading_control", "clear_kill")
        if lowered in {"/live arm", "arm live trading"}:
            return SkillMatch("trading_control", "arm_live")
        match = re.fullmatch(r"(?:/live\s+kill|activate\s+trading\s+kill\s+switch)\s+(.+)", normalized, re.IGNORECASE)
        if match:
            return SkillMatch("trading_control", "activate_kill", {"reason": match.group(1).strip()})
        return None

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation in {"status", "disarm_live", "clear_kill"}:
            return {}
        if operation == "activate_kill":
            reason = str(params.get("reason", "")).strip()
            if not reason or len(reason) > 500 or "\x00" in reason:
                raise ValueError("kill-switch reason must be 1-500 safe characters")
            return {"reason": reason}
        if operation == "arm_live":
            eligible = self._require_live_arm_preconditions()
            return {"eligible": eligible}
        raise ValueError("unknown trading-control operation")

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        if operation == "status":
            stages = {}
            for strategy_id in self.mandate.allowed_strategies:
                stage = self.promotion_store.stage(strategy_id)
                stages[strategy_id] = stage.value if stage is not None else "unregistered"
            return ExecutionResult(
                True,
                "Live trading control state",
                data={
                    "mode": self.mandate.mode.value,
                    "broker_configured": self.live_controller is not None,
                    "armed": self.live_arm.is_armed_for(self.mandate),
                    "kill_switch_active": self.kill_switch.active,
                    "kill_switch_reason": self.kill_switch.reason,
                    "strategy_stages": stages,
                },
            )

        if operation == "activate_kill":
            self.kill_switch.activate(str(params["reason"]))
            return ExecutionResult(True, "Trading kill switch activated")

        if operation == "disarm_live":
            self.live_arm.disarm()
            return ExecutionResult(True, "Live autonomous trading disarmed")

        if operation == "clear_kill":
            self.kill_switch.clear(owner_confirmed=True)
            return ExecutionResult(True, "Trading kill switch cleared")

        if operation == "arm_live":
            try:
                current_eligible = self._require_live_arm_preconditions()
            except (ValueError, PermissionError) as exc:
                return ExecutionResult(False, str(exc), error=str(exc))

            validated_eligible = tuple(str(item) for item in params["eligible"])
            if current_eligible != validated_eligible:
                return ExecutionResult(
                    False,
                    "live strategy eligibility changed after validation; submit the arm request again",
                    error="stale live-arm precondition",
                )
            self.live_arm.arm(
                self.mandate,
                owner_confirmed=True,
                live_eligible_strategies=current_eligible,
            )
            return ExecutionResult(True, "Live autonomous trading armed for the exact owner mandate")

        return ExecutionResult(False, "unknown trading-control operation", error="unknown operation")

    def _require_live_arm_preconditions(self) -> tuple[str, ...]:
        if self.live_controller is None:
            raise ValueError("no trusted live broker adapter is configured")
        if self.mandate.mode != TradingMode.LIVE_AUTONOMOUS:
            raise ValueError("trading mandate is not LIVE_AUTONOMOUS")
        if not self.mandate.allowed_strategies:
            raise ValueError("live mandate has no explicitly allowed strategies")
        ineligible = tuple(
            strategy_id
            for strategy_id in self.mandate.allowed_strategies
            if self.promotion_store.stage(strategy_id) != StrategyStage.LIVE_ELIGIBLE
        )
        if ineligible:
            raise PermissionError("live-ineligible strategies: " + ", ".join(ineligible))
        return tuple(self.mandate.allowed_strategies)
