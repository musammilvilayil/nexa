import sys
import unittest
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from core import NexaKernel, SkillRegistry
from skills.trading import (
    OrderStatus,
    PaperBroker,
    RiskEngine,
    RiskSnapshot,
    TradeSide,
    TradeSignal,
    TradingMandate,
    TradingMode,
    TradingSkill,
)


class TradingCoreTests(unittest.TestCase):
    def _mandate(self, **overrides):
        values = {
            "mode": TradingMode.PAPER_AUTONOMOUS,
            "allowed_symbols": ("nifty", "reliance"),
            "max_notional_per_trade": 100_000.0,
            "max_total_exposure": 250_000.0,
            "max_risk_per_trade": 2_000.0,
            "max_daily_loss": 5_000.0,
            "max_open_positions": 5,
            "min_signal_confidence": 0.60,
            "allow_short": False,
            "require_stop_loss": True,
        }
        values.update(overrides)
        return TradingMandate(**values)

    def _buy_signal(self, **overrides):
        values = {
            "symbol": "NIFTY",
            "side": TradeSide.BUY,
            "price": 100.0,
            "stop_loss": 98.0,
            "take_profit": 105.0,
            "confidence": 0.80,
            "strategy_id": "breakout_v1",
        }
        values.update(overrides)
        return TradeSignal(**values)

    def test_mandate_normalizes_symbols(self):
        mandate = self._mandate(allowed_symbols=(" nifty ", "RELIANCE", "nifty"))
        self.assertEqual(mandate.allowed_symbols, ("NIFTY", "RELIANCE"))

    def test_risk_engine_approves_valid_trade(self):
        decision = RiskEngine().evaluate(
            self._buy_signal(),
            10,
            self._mandate(),
            RiskSnapshot(),
        )
        self.assertTrue(decision.approved)
        self.assertEqual(decision.approved_quantity, 10)

    def test_risk_engine_rejects_unlisted_symbol(self):
        decision = RiskEngine().evaluate(
            self._buy_signal(symbol="UNKNOWN"),
            10,
            self._mandate(),
            RiskSnapshot(),
        )
        self.assertFalse(decision.approved)
        self.assertIn("not allowed", decision.reason)

    def test_risk_engine_rejects_daily_loss_ceiling(self):
        decision = RiskEngine().evaluate(
            self._buy_signal(),
            10,
            self._mandate(max_daily_loss=500.0),
            RiskSnapshot(realized_pnl_today=-500.0),
        )
        self.assertFalse(decision.approved)
        self.assertIn("daily loss", decision.reason)

    def test_risk_engine_rejects_excess_per_trade_risk(self):
        decision = RiskEngine().evaluate(
            self._buy_signal(price=100.0, stop_loss=90.0),
            10,
            self._mandate(max_risk_per_trade=50.0),
            RiskSnapshot(),
        )
        self.assertFalse(decision.approved)
        self.assertIn("per-trade risk", decision.reason)

    def test_short_selling_is_blocked_when_not_authorized(self):
        signal = self._buy_signal(side=TradeSide.SELL, stop_loss=102.0)
        decision = RiskEngine().evaluate(signal, 10, self._mandate(), RiskSnapshot())
        self.assertFalse(decision.approved)
        self.assertIn("short selling", decision.reason)

    def test_paper_broker_models_slippage_and_fees(self):
        broker = PaperBroker(fee_bps=2.0, slippage_bps=10.0)
        order = broker.place_order(
            self._buy_signal(),
            10,
            self._mandate(),
            RiskSnapshot(),
        )
        self.assertEqual(order.status, OrderStatus.FILLED)
        self.assertGreater(order.fill_price, order.requested_price)
        self.assertGreater(order.fee, 0.0)
        self.assertEqual(len(broker.orders), 1)

    def test_trading_skill_runs_through_kernel(self):
        registry = SkillRegistry()
        registry.register(TradingSkill(self._mandate()))
        kernel = NexaKernel(registry=registry)

        status = kernel.process("trading status")
        self.assertEqual(status.status, "success")
        self.assertEqual(status.result.data["mode"], "paper_autonomous")

        order = kernel.process(
            "paper buy NIFTY 10 at 100 stop 98 target 105 confidence 0.80 strategy breakout_v1"
        )
        self.assertEqual(order.status, "success")
        self.assertEqual(order.result.data["status"], "filled")

    def test_live_order_phrase_has_no_registered_execution_path(self):
        registry = SkillRegistry()
        registry.register(TradingSkill(self._mandate()))
        kernel = NexaKernel(registry=registry)

        response = kernel.process("live buy NIFTY 10 at 100")
        self.assertEqual(response.status, "no_match")


if __name__ == "__main__":
    unittest.main()
