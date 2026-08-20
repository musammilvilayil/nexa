from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

from .market import MarketSeries
from .models import OrderStatus, TradeSide, TradeSignal, TradingMandate, TradingMode
from .paper import PaperBroker
from .sizing import FixedRiskSizer
from .strategy import Strategy


@dataclass(frozen=True)
class BacktestTrade:
    symbol: str
    side: TradeSide
    quantity: int
    entry_time: datetime
    exit_time: datetime
    entry_price: float
    exit_price: float
    entry_fee: float
    exit_fee: float
    gross_pnl: float
    net_pnl: float
    exit_reason: str
    strategy_id: str


@dataclass(frozen=True)
class EquityPoint:
    timestamp: datetime
    equity: float


@dataclass(frozen=True)
class BacktestReport:
    symbol: str
    strategy_id: str
    initial_equity: float
    final_equity: float
    trades: tuple[BacktestTrade, ...]
    equity_curve: tuple[EquityPoint, ...]
    rejected_orders: int


@dataclass
class _OpenTrade:
    side: TradeSide
    quantity: int
    entry_time: datetime
    entry_price: float
    entry_fee: float
    stop_loss: float | None
    take_profit: float | None
    strategy_id: str


class BacktestEngine:
    """Single-symbol event backtester with next-bar execution.

    A signal may only be generated after a bar closes and is executed at the next
    bar's open. This prevents the most common same-bar look-ahead mistake. The
    owner mandate's risk limits remain active, but RESEARCH mode is converted to
    an internal PAPER_AUTONOMOUS simulation mandate so research can actually be
    evaluated without enabling any external execution path.
    """

    def __init__(
        self,
        *,
        fee_bps: float = 2.0,
        slippage_bps: float = 1.0,
        sizer: FixedRiskSizer | None = None,
    ) -> None:
        self.fee_bps = fee_bps
        self.slippage_bps = slippage_bps
        self.sizer = sizer or FixedRiskSizer()

    def run(
        self,
        series: MarketSeries,
        strategy: Strategy,
        mandate: TradingMandate,
        *,
        initial_equity: float = 100_000.0,
    ) -> BacktestReport:
        if initial_equity <= 0:
            raise ValueError("initial_equity must be positive")
        if len(series.candles) < 2:
            raise ValueError("backtest requires at least two bars")

        simulation_mandate = (
            replace(mandate, mode=TradingMode.PAPER_AUTONOMOUS)
            if mandate.mode == TradingMode.RESEARCH
            else mandate
        )
        broker = PaperBroker(fee_bps=self.fee_bps, slippage_bps=self.slippage_bps)
        pending_signal: TradeSignal | None = None
        open_trade: _OpenTrade | None = None
        trades: list[BacktestTrade] = []
        equity_curve: list[EquityPoint] = []
        rejected_orders = 0

        for index, bar in enumerate(series.candles):
            prices = {series.symbol: bar.close}

            if open_trade is not None:
                exit_price, exit_reason = self._exit_trigger(open_trade, bar.high, bar.low)
                if exit_price is not None:
                    trade, open_trade, rejected = self._close_trade(
                        broker,
                        simulation_mandate,
                        series.symbol,
                        open_trade,
                        bar.timestamp,
                        exit_price,
                        exit_reason,
                    )
                    rejected_orders += rejected
                    if trade is not None:
                        trades.append(trade)

            if index > 0 and open_trade is None and pending_signal is not None:
                execution_signal = self._reprice_for_next_open(pending_signal, bar.open)
                snapshot = broker.portfolio.snapshot({series.symbol: bar.open})
                quantity = self.sizer.size(execution_signal, simulation_mandate, snapshot)
                if quantity > 0:
                    order = broker.place_order(execution_signal, quantity, simulation_mandate, snapshot)
                    if order.status == OrderStatus.FILLED and order.fill_price is not None:
                        open_trade = _OpenTrade(
                            side=execution_signal.side,
                            quantity=order.quantity,
                            entry_time=bar.timestamp,
                            entry_price=order.fill_price,
                            entry_fee=order.fee,
                            stop_loss=execution_signal.stop_loss,
                            take_profit=execution_signal.take_profit,
                            strategy_id=execution_signal.strategy_id,
                        )
                    else:
                        rejected_orders += 1
                pending_signal = None

            if open_trade is None and index + 1 < len(series.candles):
                history = series.upto(index + 1)
                if len(history.candles) >= strategy.minimum_bars:
                    pending_signal = strategy.evaluate(history).signal

            equity = (
                initial_equity
                + broker.portfolio.realized_pnl_total
                + broker.portfolio.unrealized_pnl(prices)
            )
            equity_curve.append(EquityPoint(bar.timestamp, equity))

        if open_trade is not None:
            final_bar = series.last
            trade, open_trade, rejected = self._close_trade(
                broker,
                simulation_mandate,
                series.symbol,
                open_trade,
                final_bar.timestamp,
                final_bar.close,
                "end_of_data",
            )
            rejected_orders += rejected
            if trade is not None:
                trades.append(trade)
            equity_curve[-1] = EquityPoint(
                final_bar.timestamp,
                initial_equity + broker.portfolio.realized_pnl_total,
            )

        final_equity = equity_curve[-1].equity
        return BacktestReport(
            symbol=series.symbol,
            strategy_id=strategy.strategy_id,
            initial_equity=initial_equity,
            final_equity=final_equity,
            trades=tuple(trades),
            equity_curve=tuple(equity_curve),
            rejected_orders=rejected_orders,
        )

    @staticmethod
    def _reprice_for_next_open(signal: TradeSignal, open_price: float) -> TradeSignal:
        stop_loss = None
        take_profit = None
        if signal.stop_loss is not None:
            stop_distance = abs(signal.price - signal.stop_loss)
            stop_loss = open_price - stop_distance if signal.side == TradeSide.BUY else open_price + stop_distance
        if signal.take_profit is not None:
            target_distance = abs(signal.take_profit - signal.price)
            take_profit = open_price + target_distance if signal.side == TradeSide.BUY else open_price - target_distance
            if take_profit <= 0:
                take_profit = None
        return TradeSignal(
            symbol=signal.symbol,
            side=signal.side,
            price=open_price,
            confidence=signal.confidence,
            strategy_id=signal.strategy_id,
            stop_loss=stop_loss,
            take_profit=take_profit,
            generated_at_utc=signal.generated_at_utc,
        )

    @staticmethod
    def _exit_trigger(open_trade: _OpenTrade, high: float, low: float) -> tuple[float | None, str]:
        stop = open_trade.stop_loss
        target = open_trade.take_profit
        if open_trade.side == TradeSide.BUY:
            if stop is not None and low <= stop:
                return stop, "stop_loss"
            if target is not None and high >= target:
                return target, "take_profit"
        else:
            if stop is not None and high >= stop:
                return stop, "stop_loss"
            if target is not None and low <= target:
                return target, "take_profit"
        return None, ""

    @staticmethod
    def _close_trade(
        broker: PaperBroker,
        mandate: TradingMandate,
        symbol: str,
        open_trade: _OpenTrade,
        exit_time: datetime,
        exit_price: float,
        reason: str,
    ) -> tuple[BacktestTrade | None, None | _OpenTrade, int]:
        exit_side = TradeSide.SELL if open_trade.side == TradeSide.BUY else TradeSide.BUY
        signal = TradeSignal(
            symbol=symbol,
            side=exit_side,
            price=exit_price,
            confidence=1.0,
            strategy_id=open_trade.strategy_id,
        )
        snapshot = broker.portfolio.snapshot({symbol: exit_price})
        order = broker.place_order(signal, open_trade.quantity, mandate, snapshot)
        if order.status != OrderStatus.FILLED or order.fill_price is None:
            return None, open_trade, 1

        if open_trade.side == TradeSide.BUY:
            gross = (order.fill_price - open_trade.entry_price) * open_trade.quantity
        else:
            gross = (open_trade.entry_price - order.fill_price) * open_trade.quantity
        net = gross - open_trade.entry_fee - order.fee
        return (
            BacktestTrade(
                symbol=symbol,
                side=open_trade.side,
                quantity=open_trade.quantity,
                entry_time=open_trade.entry_time,
                exit_time=exit_time,
                entry_price=open_trade.entry_price,
                exit_price=order.fill_price,
                entry_fee=open_trade.entry_fee,
                exit_fee=order.fee,
                gross_pnl=gross,
                net_pnl=net,
                exit_reason=reason,
                strategy_id=open_trade.strategy_id,
            ),
            None,
            0,
        )
