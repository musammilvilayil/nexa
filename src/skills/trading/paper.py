from __future__ import annotations

from uuid import uuid4

from .models import OrderStatus, PaperOrder, RiskSnapshot, TradeSide, TradeSignal, TradingMandate
from .risk import RiskEngine


class PaperBroker:
    """Local paper-only execution engine with simple fee and slippage modelling."""

    def __init__(
        self,
        risk_engine: RiskEngine | None = None,
        *,
        fee_bps: float = 2.0,
        slippage_bps: float = 1.0,
    ) -> None:
        if fee_bps < 0 or slippage_bps < 0:
            raise ValueError("fee_bps and slippage_bps cannot be negative")
        self.risk_engine = risk_engine or RiskEngine()
        self.fee_bps = float(fee_bps)
        self.slippage_bps = float(slippage_bps)
        self._orders: list[PaperOrder] = []

    @property
    def orders(self) -> tuple[PaperOrder, ...]:
        return tuple(self._orders)

    def place_order(
        self,
        signal: TradeSignal,
        quantity: int,
        mandate: TradingMandate,
        snapshot: RiskSnapshot,
    ) -> PaperOrder:
        decision = self.risk_engine.evaluate(signal, quantity, mandate, snapshot)
        order_id = uuid4().hex[:12]

        if not decision.approved:
            order = PaperOrder(
                order_id=order_id,
                symbol=signal.symbol,
                side=signal.side,
                quantity=quantity,
                requested_price=signal.price,
                fill_price=None,
                fee=0.0,
                status=OrderStatus.REJECTED,
                reason=decision.reason,
            )
            self._orders.append(order)
            return order

        slip = signal.price * (self.slippage_bps / 10_000.0)
        fill_price = signal.price + slip if signal.side == TradeSide.BUY else signal.price - slip
        fee = fill_price * quantity * (self.fee_bps / 10_000.0)

        order = PaperOrder(
            order_id=order_id,
            symbol=signal.symbol,
            side=signal.side,
            quantity=decision.approved_quantity,
            requested_price=signal.price,
            fill_price=fill_price,
            fee=fee,
            status=OrderStatus.FILLED,
            reason=decision.reason,
        )
        self._orders.append(order)
        return order
