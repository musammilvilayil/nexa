import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from control_plane import RuntimeControlPlane
from core import NexaKernel, SkillRegistry
from input_adapters import InputEvent, KernelInputRouter, VoiceTranscriptAdapter
from local_api import _is_loopback_host
from runtime import build_runtime, build_runtime_from_trusted_brokers
from skills.dummy_skill import DummySkill
from skills.trading import (
    BrokerFactoryRegistry,
    BrokerHealth,
    BrokerSelection,
    LiveOrderResult,
    PaperBroker,
    PaperCycleResult,
    PaperEvidenceStore,
    PaperRuntimeService,
    PaperStateStore,
    RiskSnapshot,
    TradeSide,
    TradeSignal,
    TradingMandate,
    TradingMode,
    build_selected_trusted_broker,
)


def _mandate(mode=TradingMode.PAPER_AUTONOMOUS):
    return TradingMandate(
        mode=mode,
        allowed_symbols=("ABC",),
        allowed_strategies=("strategy_a",),
        max_notional_per_trade=10_000.0,
        max_total_exposure=25_000.0,
        max_risk_per_trade=500.0,
        max_daily_loss=1_000.0,
        max_open_positions=3,
        min_signal_confidence=0.5,
        allow_short=False,
        require_stop_loss=True,
    )


class FakeBroker:
    name = "fake-reviewed"

    def health(self):
        return BrokerHealth(True, "ok")

    def risk_snapshot(self, prices):
        return RiskSnapshot()

    def submit_order(self, request):
        return LiveOrderResult(True, "fake-order", "accepted", request.quantity, request.reference_price, "ok")


class PaperPersistenceTests(unittest.TestCase):
    def test_paper_state_survives_restart_with_protective_context(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "paper.db"
            store = PaperStateStore(db)
            broker = PaperBroker(state_store=store, fee_bps=0.0, slippage_bps=0.0)
            signal = TradeSignal(
                symbol="ABC",
                side=TradeSide.BUY,
                price=100.0,
                confidence=1.0,
                strategy_id="strategy_a",
                stop_loss=95.0,
                take_profit=110.0,
                generated_at_utc=datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc),
            )
            order = broker.place_order(signal, 5, _mandate())
            self.assertTrue(order.fill_price is not None)
            last = datetime(2026, 8, 20, 9, 5, tzinfo=timezone.utc)
            broker.persist_runtime_state(
                last_processed={"ABC": last},
                protective_signals={"ABC": signal},
                trading_date=date(2026, 8, 20),
            )

            restored_store = PaperStateStore(db)
            restored_broker = PaperBroker(state_store=restored_store)
            restored = restored_store.load()
            self.assertEqual(restored_broker.portfolio.position_quantity("ABC"), 5)
            self.assertEqual(len(restored_broker.orders), 1)
            self.assertEqual(dict(restored.last_processed)["ABC"], last)
            self.assertEqual(dict(restored.protective_signals)["ABC"].stop_loss, 95.0)

    def test_paper_evidence_reconstructs_closed_trade(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "paper.db"
            state = PaperStateStore(db)
            evidence = PaperEvidenceStore(db, initial_equity=100_000.0)
            broker = PaperBroker(state_store=state, fee_bps=0.0, slippage_bps=0.0)
            buy = TradeSignal(
                "ABC", TradeSide.BUY, 100.0, 1.0, "strategy_a", stop_loss=95.0
            )
            sell = TradeSignal(
                "ABC", TradeSide.SELL, 110.0, 1.0, "strategy_a", stop_loss=115.0
            )
            broker.place_order(buy, 5, _mandate())
            broker.place_order(sell, 5, _mandate())
            evidence.record_activity(date(2026, 8, 20))
            report = evidence.report()
            self.assertTrue(report.consistent)
            self.assertEqual(report.evidence.trading_days, 1)
            self.assertEqual(report.evidence.closed_trades, 1)
            self.assertAlmostEqual(report.evidence.net_pnl, 50.0)


class PaperServiceTests(unittest.TestCase):
    def test_provider_failure_is_reported_not_synthesized(self):
        class Provider:
            def load(self, symbol):
                raise RuntimeError("feed unavailable")

        class Brain:
            mandate = _mandate()

            def arm_paper_runtime(self):
                return None

            def on_market_update(self, series):
                return PaperCycleResult("no_trade", "unused")

        service = PaperRuntimeService(Brain(), Provider(), ("ABC",))
        cycle = service.run_cycle()
        self.assertFalse(cycle.ok)
        self.assertIn("feed unavailable", cycle.symbols[0].error)


class BrokerBoundaryTests(unittest.TestCase):
    def test_environment_selector_requires_explicit_trusted_registry(self):
        registry = BrokerFactoryRegistry({"reviewed": lambda selection: FakeBroker()})
        broker = build_selected_trusted_broker(
            registry,
            selection=BrokerSelection("reviewed", "primary"),
        )
        self.assertEqual(broker.name, "fake-reviewed")
        with self.assertRaises(PermissionError):
            build_selected_trusted_broker(
                registry,
                selection=BrokerSelection("not_registered"),
            )

    def test_default_runtime_does_not_auto_enable_broker_from_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {
                "NEXA_AUDIT_DB": str(Path(temp) / "audit.db"),
                "NEXA_STRATEGY_DB": str(Path(temp) / "strategy.db"),
                "NEXA_PAPER_DB": str(Path(temp) / "paper.db"),
                "NEXA_LIVE_BROKER_PROVIDER": "reviewed",
            }
            with patch.dict(os.environ, env, clear=False):
                runtime = build_runtime()
            self.assertIsNone(runtime.live_controller)

    def test_explicit_trusted_runtime_path_wires_broker_but_stays_disarmed(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {
                "NEXA_AUDIT_DB": str(Path(temp) / "audit.db"),
                "NEXA_STRATEGY_DB": str(Path(temp) / "strategy.db"),
                "NEXA_PAPER_DB": str(Path(temp) / "paper.db"),
                "NEXA_TRADING_MODE": "research",
            }
            registry = BrokerFactoryRegistry({"reviewed": lambda selection: FakeBroker()})
            with patch.dict(os.environ, env, clear=False):
                runtime = build_runtime_from_trusted_brokers(
                    registry,
                    selection=BrokerSelection("reviewed"),
                )
            self.assertIsNotNone(runtime.live_controller)
            self.assertFalse(runtime.live_arm.armed)


class ControlAndInputBoundaryTests(unittest.TestCase):
    def test_voice_transcript_hits_kernel_confirmation_gate(self):
        registry = SkillRegistry()
        registry.register(DummySkill())
        runtime = SimpleNamespace(kernel=NexaKernel(registry=registry))
        control = RuntimeControlPlane(runtime)
        adapter = VoiceTranscriptAdapter(lambda: "publish origin")
        event = adapter.next_event()
        self.assertIsNotNone(event)
        result = KernelInputRouter(control).route(event)
        self.assertTrue(result.handled_by_kernel)
        self.assertEqual(result.payload["status"], "confirmation_required")

    def test_runtime_health_and_shutdown_hooks(self):
        with tempfile.TemporaryDirectory() as temp:
            env = {
                "NEXA_AUDIT_DB": str(Path(temp) / "audit.db"),
                "NEXA_STRATEGY_DB": str(Path(temp) / "strategy.db"),
                "NEXA_PAPER_DB": str(Path(temp) / "paper.db"),
            }
            with patch.dict(os.environ, env, clear=False):
                runtime = build_runtime()
            control = RuntimeControlPlane(runtime)
            snapshot = control.health()
            self.assertTrue(snapshot.ok)
            self.assertEqual(control.status()["state"], "ready")
            control.shutdown()
            self.assertTrue(control.stopped)
            self.assertEqual(control.status()["state"], "stopped")
            self.assertFalse(runtime.live_arm.armed)

    def test_local_api_loopback_guard(self):
        self.assertTrue(_is_loopback_host("127.0.0.1"))
        self.assertTrue(_is_loopback_host("::1"))
        self.assertTrue(_is_loopback_host("localhost"))
        self.assertFalse(_is_loopback_host("0.0.0.0"))


if __name__ == "__main__":
    unittest.main()
