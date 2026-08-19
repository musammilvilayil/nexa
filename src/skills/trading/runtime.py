from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .market import MarketSeries, validate_market_series
from .models import OrderStatus, PaperOrder, TradeSide, TradeSignal, TradingMandate, TradingMode
from .paper import PaperBroker
from .sizing import FixedRiskSizer
from .strategy import Strategy, StrategyDecision


@dataclass(frozen=True)
class PaperCycleResult:
    status: str
    reason: str
    strategy_decision: StrategyDecision | None = None
    order: PaperOrder | None = None


class AutonomousPaperTrader:
    """Bounded autonomous paper loop.

    This runtime can enter and exit paper positions without per-order user
    confirmation, but only inside an owner mandate and only through RiskEngine.
    It has no live-broker execution path.
    """

    def __init__(
        self,
        mandate: TradingMandate,
        strategy: Strategy,
        *,
        broker: PaperBroker | None = None,
        sizer: FixedRiskSizer | None = None,
        max_market_age_seconds: float | None = None,
    ) -> None:
        self.mandate = mandate
        self.strategy = strategy
        self.broker = broker or PaperBroker()
        self.sizer = sizer or FixedRiskSizer()
        self.max_market_age_seconds = max_market_age_seconds
        self._last_processed: dict[str, datetime] = {}
        self._protective: dict[str, TradeSignal] = {}

    def on_market_update(
        self,
        series: MarketSeries,
        *,
        now: datetime | None = None,
    ) -> PaperCycleResult:
        if self.mandate.mode != TradingMode.PAPER_AUTONOMOUS:
            return PaperCycleResult("disabled", f"autonomous paper loop disabled in {self.mandate.mode.value}")

        current_now = now or datetime.now(timezone.utc)
        quality = validate_market_series(
            series,
            now=current_now,
            max_age_seconds=self.max_market_age_seconds,
            min_bars=self.strategy.minimum_bars,
        )
        if not quality.valid:
            return PaperCycleResult("blocked", quality.reason)

        last_time = series.last.utc_timestamp
        if self._last_processed.get(series.symbol) == last_time:
            return PaperCycleResult("noop", "bar already processed")
        self._last_processed[series.symbol] = last_time

        current_quantity = self.broker.portfolio.position_quantity(series.symbol)
        if current_quantity != 0:
            protective = self._protective.get(series.symbol)
            trigger = self._protective_exit(protective, series.last.high, series.last.low)
            if trigger is not None:
                price, reason = trigger
                side = TradeSide.SELL if current_quantity > 0 else TradeSide.BUY
                exit_signal = TradeSignal(
                    symbol=series.symbol,
                    side=side,
                    price=price,
                    confidence=1.0,
                    strategy_id=protective.strategy_id if protective else self.strategy.strategy_id,
                )
                snapshot = self.broker.portfolio.snapshot({series.symbol: price})
                order = self.broker.place_order(exit_signal, abs(current_quantity), self.mandate, snapshot)
                if order.status == OrderStatus.FILLED:
                    self._protective.pop(series.symbol, None)
                return PaperCycleResult("exit", reason, order=order)

            return PaperCycleResult("holding", "position open; protective exits not triggered")

        decision = self.strategy.evaluate(series)
        if decision.signal is None:
            return PaperCycleResult("no_trade", decision.reason, strategy_decision=decision)

        signal = decision.signal
        snapshot = self.broker.portfolio.snapshot({series.symbol: signal.price})
        quantity = self.sizer.size(signal, self.mandate, snapshot)
        if quantity <= 0:
            return PaperCycleResult("blocked", "no admissible quantity", strategy_decision=decision)

        order = self.broker.place_order(signal, quantity, self.mandate, snapshot)
        if order.status == OrderStatus.FILLED:
            self._protective[series.symbol] = signal
            return PaperCycleResult("entered", order.reason, strategy_decision=decision, order=order)
        return PaperCycleResult("rejected", order.reason, strategy_decision=decision, order=order)

    @staticmethod
    def _protective_exit(
        signal: TradeSignal | None,
        high: float,
        low: float,
    ) -> tuple[float, str] | None:
        if signal is None:
            return None
        if signal.side == TradeSide.BUY:
            if signal.stop_loss is not None and low <= signal.stop_loss:
                return signal.stop_loss, "stop_loss"
            if signal.take_profit is not None and high >= signal.take_profit:
                return signal.take_profit, "take_profit"
        else:
            if signal.stop_loss is not None and high >= signal.stop_loss:
                return signal.stop_loss, "stop_loss"
            if signal.take_profit is not None and low <= signal.take_profit:
                return signal.take_profit, "take_profit"
        return None
