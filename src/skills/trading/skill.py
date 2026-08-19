from __future__ import annotations

import re
from typing import Any, Mapping

from core import ExecutionResult, OperationSpec, RiskTier, SkillMatch, SkillMetadata

from .models import RiskSnapshot, TradeSide, TradeSignal, TradingMandate
from .paper import PaperBroker


_PAPER_ORDER_RE = re.compile(
    r"^paper\s+(buy|sell)\s+([A-Za-z0-9._-]+)\s+(\d+)\s+at\s+([0-9]+(?:\.[0-9]+)?)"
    r"\s+stop\s+([0-9]+(?:\.[0-9]+)?)"
    r"(?:\s+target\s+([0-9]+(?:\.[0-9]+)?))?"
    r"\s+confidence\s+([0-9]+(?:\.[0-9]+)?)"
    r"\s+strategy\s+([A-Za-z0-9._-]+)$",
    re.IGNORECASE,
)


class TradingSkill:
    """Trading plugin for the standalone NEXA kernel.

    v0.1 deliberately exposes only inspection and paper execution. Live broker
    execution is not registered yet, so no model or user phrase can reach it.
    """

    def __init__(self, mandate: TradingMandate, paper_broker: PaperBroker | None = None) -> None:
        self.mandate = mandate
        self.paper_broker = paper_broker or PaperBroker()
        self.metadata = SkillMetadata(
            name="trading",
            version="0.1.0",
            description="Risk-gated trading research and paper execution",
            operations=(
                OperationSpec("status", "Inspect the active trading mandate", RiskTier.READ),
                OperationSpec("paper_order", "Submit a simulated paper order", RiskTier.MUTATE),
            ),
        )

    def match(self, text: str, context: Mapping[str, Any]) -> SkillMatch | None:
        normalized = " ".join(text.strip().split())
        if normalized.lower() in {"trading status", "trade status"}:
            return SkillMatch("trading", "status")

        match = _PAPER_ORDER_RE.fullmatch(normalized)
        if match is None:
            return None

        side, symbol, quantity, price, stop, target, confidence, strategy_id = match.groups()
        return SkillMatch(
            "trading",
            "paper_order",
            {
                "side": side.lower(),
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "stop_loss": stop,
                "take_profit": target,
                "confidence": confidence,
                "strategy_id": strategy_id,
            },
        )

    def validate(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        if operation == "status":
            return {}
        if operation != "paper_order":
            raise ValueError("unknown trading operation")

        side = TradeSide(str(params.get("side", "")).lower())
        symbol = str(params.get("symbol", "")).strip().upper()
        quantity = int(params.get("quantity", 0))
        price = float(params.get("price", 0.0))
        stop_loss = float(params["stop_loss"]) if params.get("stop_loss") is not None else None
        take_profit = float(params["take_profit"]) if params.get("take_profit") is not None else None
        confidence = float(params.get("confidence", 0.0))
        strategy_id = str(params.get("strategy_id", "")).strip()

        signal = TradeSignal(
            symbol=symbol,
            side=side,
            price=price,
            confidence=confidence,
            strategy_id=strategy_id,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

        return {"signal": signal, "quantity": quantity}

    def execute(
        self,
        operation: str,
        params: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> ExecutionResult:
        if operation == "status":
            return ExecutionResult(
                True,
                f"Trading mode: {self.mandate.mode.value}",
                data={
                    "mode": self.mandate.mode.value,
                    "allowed_symbols": self.mandate.allowed_symbols,
                    "max_notional_per_trade": self.mandate.max_notional_per_trade,
                    "max_total_exposure": self.mandate.max_total_exposure,
                    "max_risk_per_trade": self.mandate.max_risk_per_trade,
                    "max_daily_loss": self.mandate.max_daily_loss,
                },
            )

        if operation == "paper_order":
            signal = params["signal"]
            quantity = int(params["quantity"])
            order = self.paper_broker.place_order(
                signal,
                quantity,
                self.mandate,
                RiskSnapshot(),
            )
            success = order.status.value == "filled"
            return ExecutionResult(
                success,
                f"paper order {order.status.value}: {order.reason}",
                data={
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": order.side.value,
                    "quantity": order.quantity,
                    "requested_price": order.requested_price,
                    "fill_price": order.fill_price,
                    "fee": order.fee,
                    "status": order.status.value,
                },
                error=None if success else order.reason,
            )

        return ExecutionResult(False, "unknown trading operation", error="unknown operation")
