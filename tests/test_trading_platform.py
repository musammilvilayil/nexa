import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from skills.trading import (
    BrokerHealth,
    CSVMarketDataProvider,
    LiveArmController,
    LiveExecutionController,
    LiveOrderResult,
    PaperEvidence,
    PromotionPolicy,
    RiskSnapshot,
    StrategyPromotionGate,
    StrategyPromotionStore,
    StrategyStage,
    TradeSide,
    TradeSignal,
    TradingKillSwitch,
    TradingMandate,
    TradingMode,
)


class FakeBroker:
    name = "fake"

    def __init__(self, snapshot=None):
        self.snapshot = snapshot or RiskSnapshot()
        self.requests = []

    def health(self):
        return BrokerHealth(True, "ok")

    def risk_snapshot(self, prices):
        return self.snapshot

    def submit_order(self, request):
        self.requests.append(request)
        return LiveOrderResult(True, "broker-1", "accepted", request.quantity, request.reference_price, "ok")


def live_mandate():
    return TradingMandate(
        mode=TradingMode.LIVE_AUTONOMOUS,
        allowed_symbols=("NIFTY",),
        allowed_strategies=("adaptive_momentum_v1",),
        max_notional_per_trade=100_000,
        max_total_exposure=250_000,
        max_risk_per_trade=2_000,
        max_daily_loss=5_000,
        max_open_positions=3,
        min_signal_confidence=0.6,
        allow_short=False,
        require_stop_loss=True,
    )


def entry_signal(*, generated_at_utc=None):
    return TradeSignal(
        "NIFTY",
        TradeSide.BUY,
        100.0,
        0.8,
        "adaptive_momentum_v1",
        98.0,
        104.0,
        generated_at_utc or datetime.now(timezone.utc),
    )


class TradingPlatformTests(unittest.TestCase):
    def test_csv_provider_is_contained_and_requires_timezone(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "NIFTY.csv").write_text(
                "timestamp,open,high,low,close,volume\n"
                "2026-01-01T09:15:00+05:30,100,101,99,100.5,1000\n"
                "2026-01-01T09:16:00+05:30,100.5,102,100,101.5,1200\n",
                encoding="utf-8",
            )
            provider = CSVMarketDataProvider(root)
            series = provider.load("nifty")
            self.assertEqual(series.symbol, "NIFTY")
            self.assertEqual(len(series.candles), 2)
            with self.assertRaises(ValueError):
                provider.load_file("../outside.csv")

    def test_live_autonomy_needs_one_time_arm_but_not_per_trade_confirmation(self):
        with tempfile.TemporaryDirectory() as temp:
            promotion = StrategyPromotionStore(Path(temp) / "promotion.db")
            promotion.register("adaptive_momentum_v1")
            promotion.set_stage(
                "adaptive_momentum_v1",
                StrategyStage.LIVE_ELIGIBLE,
                ("test eligibility",),
            )
            arm = LiveArmController()
            broker = FakeBroker()
            controller = LiveExecutionController(
                mandate=live_mandate(),
                broker=broker,
                promotion_store=promotion,
                arm=arm,
            )

            blocked = controller.execute(entry_signal())
            self.assertFalse(blocked.accepted)
            self.assertIn("not armed", blocked.reason)

            arm.arm(
                live_mandate(),
                owner_confirmed=True,
                live_eligible_strategies=("adaptive_momentum_v1",),
            )
            first = controller.execute(entry_signal())
            second = controller.execute(entry_signal())
            self.assertTrue(first.accepted)
            self.assertTrue(second.accepted)
            self.assertEqual(len(broker.requests), 2)

    def test_stale_live_entry_activates_kill_switch_without_order(self):
        with tempfile.TemporaryDirectory() as temp:
            promotion = StrategyPromotionStore(Path(temp) / "promotion.db")
            promotion.register("adaptive_momentum_v1")
            promotion.set_stage("adaptive_momentum_v1", StrategyStage.LIVE_ELIGIBLE, ("test",))
            mandate = live_mandate()
            arm = LiveArmController()
            arm.arm(
                mandate,
                owner_confirmed=True,
                live_eligible_strategies=("adaptive_momentum_v1",),
            )
            switch = TradingKillSwitch()
            broker = FakeBroker()
            controller = LiveExecutionController(
                mandate=mandate,
                broker=broker,
                promotion_store=promotion,
                arm=arm,
                kill_switch=switch,
                max_signal_age_seconds=30,
            )
            now = datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc)
            stale = entry_signal(generated_at_utc=now - timedelta(seconds=31))

            result = controller.execute(stale, now=now)

            self.assertFalse(result.accepted)
            self.assertIn("stale", result.reason)
            self.assertTrue(switch.active)
            self.assertEqual(broker.requests, [])

    def test_mandate_change_invalidates_live_arm(self):
        arm = LiveArmController()
        original = live_mandate()
        arm.arm(
            original,
            owner_confirmed=True,
            live_eligible_strategies=("adaptive_momentum_v1",),
        )
        changed = TradingMandate(
            **{
                **original.__dict__,
                "max_notional_per_trade": 150_000,
            }
        )
        self.assertTrue(arm.is_armed_for(original))
        self.assertFalse(arm.is_armed_for(changed))

    def test_kill_switch_blocks_new_entry_but_allows_full_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            promotion = StrategyPromotionStore(Path(temp) / "promotion.db")
            promotion.register("adaptive_momentum_v1")
            promotion.set_stage("adaptive_momentum_v1", StrategyStage.LIVE_ELIGIBLE, ("test",))
            arm = LiveArmController()
            mandate = live_mandate()
            arm.arm(
                mandate,
                owner_confirmed=True,
                live_eligible_strategies=("adaptive_momentum_v1",),
            )
            switch = TradingKillSwitch()
            switch.activate("manual emergency stop")
            flat_broker = FakeBroker()
            controller = LiveExecutionController(
                mandate=mandate,
                broker=flat_broker,
                promotion_store=promotion,
                arm=arm,
                kill_switch=switch,
            )
            self.assertFalse(controller.execute(entry_signal()).accepted)

            long_snapshot = RiskSnapshot(
                total_exposure=1000,
                open_positions=1,
                open_symbols=("NIFTY",),
                position_quantities=(("NIFTY", 10),),
            )
            exit_broker = FakeBroker(long_snapshot)
            exit_controller = LiveExecutionController(
                mandate=mandate,
                broker=exit_broker,
                promotion_store=promotion,
                arm=arm,
                kill_switch=switch,
            )
            exit_signal = TradeSignal(
                "NIFTY",
                TradeSide.SELL,
                99,
                1.0,
                "adaptive_momentum_v1",
            )
            result = exit_controller.execute(exit_signal, requested_quantity=10)
            self.assertTrue(result.accepted)
            self.assertEqual(exit_broker.requests[0].quantity, 10)

    def test_promotion_gate_requires_research_paper_and_owner(self):
        policy = PromotionPolicy(min_paper_days=20, min_paper_trades=30, max_paper_drawdown_pct=15)
        gate = StrategyPromotionGate(policy)
        paper = PaperEvidence(20, 30, 1000, 5, 0)

        class Evaluation:
            passed = True
            reasons = ("passed",)

        class Report:
            evaluation = Evaluation()

        denied = gate.paper_to_live_eligible(Report(), paper, owner_approved=False)
        allowed = gate.paper_to_live_eligible(Report(), paper, owner_approved=True)
        self.assertFalse(denied.allowed)
        self.assertTrue(allowed.allowed)


if __name__ == "__main__":
    unittest.main()
