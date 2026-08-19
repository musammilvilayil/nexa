from __future__ import annotations

from uuid import uuid4

from .models import OrderStatus, PaperOrder, RiskSnapshot, TradeSide, TradeSignal, TradingMandate
from .portfolio import PaperPortfolio
from .risk import RiskEngine


class PaperBroker:
    """Local paper-only execution engine with fee, slippage, and portfolio state."""

    def __init__(
        self,
        risk_engine: RiskEngine | None = None,
        *,
        fee_bps: float = 2.0,
        slippage_bps: float = 1.0,
        portfolio: PaperPortfolio | None = None,
    ) -> None:
        if fee_bps < 0 or slippage_bps < 0:
            raise ValueError("fee_bps and slippage_bps cannot be negative")
        self.risk_engine = risk_engine or RiskEngine()
        self.fee_bps = float(fee_bps)
        self.slippage_bps = float(slippage_bps)
        self.portfolio = portfolio or PaperPortfolio()
        self._orders: list[PaperOrder] = []

    @property
    def orders(self) -> tuple[PaperOrder, ...]:
        return tuple(self._orders)

    def place_order(
        self,
        signal: TradeSignal,
        quantity: int,
        mandate: TradingMandate,
        snapshot: RiskSnapshot | None = None,
    ) -> PaperOrder:
        effective_snapshot = snapshot or self.portfolio.snapshot({signal.symbol: signal.price})
        decision = self.risk_engine.evaluate(signal, quantity, mandate, effective_snapshot)
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
        fee = fill_price * decision.approved_quantity * (self.fee_bps / 10_000.0)

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
        self.portfolio.apply_fill(
            order.symbol,
            order.side,
            order.quantity,
            fill_price,
            fee,
        )
        return order
