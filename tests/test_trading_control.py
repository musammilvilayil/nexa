import sys
import tempfile
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import ContextBus, NexaKernel, SkillRegistry
from skills.trading import (
    BrokerHealth,
    LiveArmController,
    LiveExecutionController,
    LiveOrderResult,
    RiskSnapshot,
    StrategyPromotionStore,
    StrategyStage,
    TradingControlSkill,
    TradingKillSwitch,
    TradingMandate,
    TradingMode,
)


class FakeBroker:
    name = "fake"

    def health(self):
        return BrokerHealth(True, "ok")

    def risk_snapshot(self, prices):
        return RiskSnapshot()

    def submit_order(self, request):
        return LiveOrderResult(False, None, "rejected", 0, None, "not used in control tests")


class TradingControlTests(unittest.TestCase):
    def _runtime_parts(self, root: Path):
        mandate = TradingMandate(
            mode=TradingMode.LIVE_AUTONOMOUS,
            allowed_symbols=("NIFTY50",),
            allowed_strategies=("adaptive_router_v1",),
            max_notional_per_trade=10_000,
            max_total_exposure=20_000,
            max_risk_per_trade=200,
            max_daily_loss=500,
            max_open_positions=2,
        )
        store = StrategyPromotionStore(root / "promotion.db")
        store.register("adaptive_router_v1")
        store.set_stage("adaptive_router_v1", StrategyStage.LIVE_ELIGIBLE, ("test eligible",))
        arm = LiveArmController()
        kill = TradingKillSwitch()
        controller = LiveExecutionController(
            mandate=mandate,
            broker=FakeBroker(),
            promotion_store=store,
            arm=arm,
            kill_switch=kill,
        )
        bus = ContextBus()
        skill = TradingControlSkill(
            mandate=mandate,
            promotion_store=store,
            live_arm=arm,
            kill_switch=kill,
            live_controller=controller,
        )
        registry = SkillRegistry()
        registry.register(skill)
        kernel = NexaKernel(registry=registry, context_bus=bus)
        return mandate, arm, kill, store, kernel

    def test_live_arm_is_confirmation_gated(self):
        with tempfile.TemporaryDirectory() as temp:
            mandate, arm, _, _, kernel = self._runtime_parts(Path(temp))
            pending = kernel.process("/live arm")
            self.assertEqual(pending.status, "confirmation_required")
            self.assertFalse(arm.is_armed_for(mandate))

            result = kernel.confirm(pending.pending_action.action_id)
            self.assertEqual(result.status, "success")
            self.assertTrue(arm.is_armed_for(mandate))

    def test_live_arm_fails_if_strategy_loses_eligibility_while_pending(self):
        with tempfile.TemporaryDirectory() as temp:
            mandate, arm, _, store, kernel = self._runtime_parts(Path(temp))
            pending = kernel.process("/live arm")
            self.assertEqual(pending.status, "confirmation_required")

            store.disable("adaptive_router_v1", "safety regression")
            result = kernel.confirm(pending.pending_action.action_id)

            self.assertEqual(result.status, "failure")
            self.assertIn("live-ineligible", result.message)
            self.assertFalse(arm.is_armed_for(mandate))

    def test_kill_activation_is_immediate_but_clear_is_confirmation_gated(self):
        with tempfile.TemporaryDirectory() as temp:
            _, _, kill, _, kernel = self._runtime_parts(Path(temp))
            activated = kernel.process("/live kill stale market data")
            self.assertEqual(activated.status, "success")
            self.assertTrue(kill.active)

            pending = kernel.process("/live clear-kill")
            self.assertEqual(pending.status, "confirmation_required")
            self.assertTrue(kill.active)

            cleared = kernel.confirm(pending.pending_action.action_id)
            self.assertEqual(cleared.status, "success")
            self.assertFalse(kill.active)

    def test_disarm_is_immediate_risk_reduction(self):
        with tempfile.TemporaryDirectory() as temp:
            mandate, arm, _, _, kernel = self._runtime_parts(Path(temp))
            pending = kernel.process("/live arm")
            kernel.confirm(pending.pending_action.action_id)
            self.assertTrue(arm.is_armed_for(mandate))

            disarmed = kernel.process("/live disarm")
            self.assertEqual(disarmed.status, "success")
            self.assertFalse(arm.armed)


if __name__ == "__main__":
    unittest.main()
