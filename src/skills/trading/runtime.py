from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

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

    If the supplied ``PaperBroker`` has a persistent state store, duplicate-bar
    guards, protective stops/targets, positions, orders, and daily PnL state are
    restored automatically after a process restart.
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
        self._trading_date: date | None = None

        if self.broker.state_store is not None:
            restored = self.broker.state_store.load()
            self._last_processed = dict(restored.last_processed)
            self._protective = dict(restored.protective_signals)
            self._trading_date = restored.trading_date

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

        trading_date = series.last.timestamp.date()
        if self._trading_date != trading_date:
            self.broker.portfolio.reset_daily_pnl()
            self._trading_date = trading_date
            self._persist_runtime()

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
                    generated_at_utc=series.last.utc_timestamp,
                )
                snapshot = self.broker.portfolio.snapshot({series.symbol: price})
                order = self.broker.place_order(exit_signal, abs(current_quantity), self.mandate, snapshot)
                if order.status == OrderStatus.FILLED:
                    self._protective.pop(series.symbol, None)
                return self._finish(PaperCycleResult("exit", reason, order=order))

            return self._finish(PaperCycleResult("holding", "position open; protective exits not triggered"))

        decision = self.strategy.evaluate(series)
        if decision.signal is None:
            return self._finish(PaperCycleResult("no_trade", decision.reason, strategy_decision=decision))

        signal = decision.signal
        snapshot = self.broker.portfolio.snapshot({series.symbol: signal.price})
        quantity = self.sizer.size(signal, self.mandate, snapshot)
        if quantity <= 0:
            return self._finish(
                PaperCycleResult("blocked", "no admissible quantity", strategy_decision=decision)
            )

        order = self.broker.place_order(signal, quantity, self.mandate, snapshot)
        if order.status == OrderStatus.FILLED:
            self._protective[series.symbol] = signal
            return self._finish(
                PaperCycleResult("entered", order.reason, strategy_decision=decision, order=order)
            )
        return self._finish(
            PaperCycleResult("rejected", order.reason, strategy_decision=decision, order=order)
        )

    def _finish(self, result: PaperCycleResult) -> PaperCycleResult:
        self._persist_runtime()
        return result

    def _persist_runtime(self) -> None:
        self.broker.persist_runtime_state(
            last_processed=self._last_processed,
            protective_signals=self._protective,
            trading_date=self._trading_date,
        )

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
