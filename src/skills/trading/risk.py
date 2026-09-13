from __future__ import annotations

from .models import RiskDecision, RiskSnapshot, TradeSide, TradeSignal, TradingMandate, TradingMode


class RiskEngine:
    """Deterministic pre-trade authority that strategies cannot bypass."""

    def evaluate(
        self,
        signal: TradeSignal,
        quantity: int,
        mandate: TradingMandate,
        snapshot: RiskSnapshot,
    ) -> RiskDecision:
        if quantity <= 0:
            return RiskDecision(False, "quantity must be positive")

        current_quantity = snapshot.position_quantity(signal.symbol)
        reducing = self._is_pure_risk_reducing(signal.side, quantity, current_quantity)
        if reducing:
            # Pure exits are evaluated before mode/symbol/strategy/loss gates so
            # disabling a strategy, changing mode, shrinking the universe, or
            # hitting a loss ceiling cannot trap existing exposure.
            return RiskDecision(True, "approved risk-reducing exit", quantity)

        if mandate.mode == TradingMode.RESEARCH:
            return RiskDecision(False, "research mode cannot place external/paper orders")

        if signal.symbol not in mandate.allowed_symbols:
            return RiskDecision(False, f"symbol not allowed: {signal.symbol}")

        if mandate.allowed_strategies and signal.strategy_id not in mandate.allowed_strategies:
            return RiskDecision(False, f"strategy not authorized: {signal.strategy_id}")

        if signal.confidence < mandate.min_signal_confidence:
            return RiskDecision(False, "signal confidence below mandate minimum")

        if snapshot.realized_pnl_today <= -mandate.max_daily_loss:
            return RiskDecision(False, "daily loss ceiling reached")

        already_open = current_quantity != 0 or signal.symbol in snapshot.open_symbols

        if signal.side == TradeSide.SELL and not mandate.allow_short:
            if current_quantity <= 0 or quantity > current_quantity:
                return RiskDecision(False, "short selling is not allowed by mandate")

        if not already_open and snapshot.open_positions >= mandate.max_open_positions:
            return RiskDecision(False, "maximum open positions reached")

        if mandate.require_stop_loss and signal.stop_loss is None:
            return RiskDecision(False, "stop loss required by mandate")

        if signal.stop_loss is not None:
            if signal.side == TradeSide.BUY and signal.stop_loss >= signal.price:
                return RiskDecision(False, "buy stop loss must be below entry price")
            if signal.side == TradeSide.SELL and signal.stop_loss <= signal.price:
                return RiskDecision(False, "sell stop loss must be above entry price")

            risk_amount = abs(signal.price - signal.stop_loss) * quantity
            if risk_amount > mandate.max_risk_per_trade:
                return RiskDecision(False, "per-trade risk limit exceeded")

        if signal.take_profit is not None:
            if signal.side == TradeSide.BUY and signal.take_profit <= signal.price:
                return RiskDecision(False, "buy take profit must be above entry price")
            if signal.side == TradeSide.SELL and signal.take_profit >= signal.price:
                return RiskDecision(False, "sell take profit must be below entry price")

        notional = signal.price * quantity
        if notional > mandate.max_notional_per_trade:
            return RiskDecision(False, "per-trade notional limit exceeded")

        if snapshot.total_exposure + notional > mandate.max_total_exposure:
            return RiskDecision(False, "total exposure limit exceeded")

        return RiskDecision(True, "approved by risk mandate", quantity)

    @staticmethod
    def _is_pure_risk_reducing(side: TradeSide, quantity: int, current_quantity: int) -> bool:
        if current_quantity > 0 and side == TradeSide.SELL:
            return quantity <= current_quantity
        if current_quantity < 0 and side == TradeSide.BUY:
            return quantity <= abs(current_quantity)
        return False
