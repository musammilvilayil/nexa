from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Mapping, Protocol
from uuid import uuid4

from .journal import TradingJournal
from .models import RiskSnapshot, TradeSide, TradeSignal, TradingMandate, TradingMode
from .promotion import StrategyPromotionStore, StrategyStage
from .risk import RiskEngine
from .sizing import FixedRiskSizer


@dataclass(frozen=True)
class BrokerHealth:
    ok: bool
    reason: str = ""


@dataclass(frozen=True)
class LiveOrderRequest:
    client_order_id: str
    symbol: str
    side: TradeSide
    quantity: int
    reference_price: float
    strategy_id: str
    stop_loss: float | None = None
    take_profit: float | None = None


@dataclass(frozen=True)
class LiveOrderResult:
    accepted: bool
    order_id: str | None
    status: str
    filled_quantity: int
    average_price: float | None
    reason: str


class BrokerAdapter(Protocol):
    @property
    def name(self) -> str:
        ...

    def health(self) -> BrokerHealth:
        ...

    def risk_snapshot(self, prices: Mapping[str, float]) -> RiskSnapshot:
        ...

    def submit_order(self, request: LiveOrderRequest) -> LiveOrderResult:
        ...


class TradingKillSwitch:
    """Blocks new live exposure while still permitting pure risk-reducing exits."""

    def __init__(self) -> None:
        self._active = False
        self._reason = ""

    @property
    def active(self) -> bool:
        return self._active

    @property
    def reason(self) -> str:
        return self._reason

    def activate(self, reason: str) -> None:
        message = reason.strip()
        if not message:
            raise ValueError("kill-switch reason required")
        self._active = True
        self._reason = message

    def clear(self, *, owner_confirmed: bool) -> None:
        if not owner_confirmed:
            raise PermissionError("owner confirmation required to clear kill switch")
        self._active = False
        self._reason = ""


class LiveArmController:
    """One-time session arm for an owner-approved LIVE_AUTONOMOUS mandate.

    Arming is intentionally in-memory and invalidates automatically if any mandate
    field changes. It removes per-trade confirmation without making changed limits
    silently valid after a restart or configuration edit.
    """

    def __init__(self) -> None:
        self._fingerprint: str | None = None

    @property
    def armed(self) -> bool:
        return self._fingerprint is not None

    def arm(
        self,
        mandate: TradingMandate,
        *,
        owner_confirmed: bool,
        live_eligible_strategies: tuple[str, ...],
    ) -> None:
        if not owner_confirmed:
            raise PermissionError("owner confirmation required to arm live autonomy")
        if mandate.mode != TradingMode.LIVE_AUTONOMOUS:
            raise ValueError("mandate must be LIVE_AUTONOMOUS to arm live execution")
        allowed = set(mandate.allowed_strategies)
        eligible = set(live_eligible_strategies)
        if not allowed:
            raise ValueError("live mandate must explicitly allow at least one strategy")
        missing = sorted(allowed - eligible)
        if missing:
            raise PermissionError(f"strategies are not live eligible: {', '.join(missing)}")
        self._fingerprint = mandate_fingerprint(mandate)

    def disarm(self) -> None:
        self._fingerprint = None

    def is_armed_for(self, mandate: TradingMandate) -> bool:
        return self._fingerprint == mandate_fingerprint(mandate)


def mandate_fingerprint(mandate: TradingMandate) -> str:
    payload = asdict(mandate)
    payload["mode"] = mandate.mode.value
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class LiveExecutionController:
    """Mandate-bound autonomous live execution boundary.

    No user confirmation occurs per ordinary order after the session is armed.
    Every new entry still requires a fresh timestamped signal, broker health,
    live-eligible strategy state, position sizing, and RiskEngine approval. A
    stale/missing live-entry signal activates the kill switch. Risk-reducing exits
    remain possible even while the switch is active or market data is stale.
    """

    def __init__(
        self,
        *,
        mandate: TradingMandate,
        broker: BrokerAdapter,
        promotion_store: StrategyPromotionStore,
        arm: LiveArmController,
        kill_switch: TradingKillSwitch | None = None,
        risk_engine: RiskEngine | None = None,
        sizer: FixedRiskSizer | None = None,
        journal: TradingJournal | None = None,
        max_signal_age_seconds: float = 60.0,
        future_signal_tolerance_seconds: float = 5.0,
    ) -> None:
        if not math.isfinite(max_signal_age_seconds) or max_signal_age_seconds <= 0:
            raise ValueError("max_signal_age_seconds must be positive and finite")
        if not math.isfinite(future_signal_tolerance_seconds) or future_signal_tolerance_seconds < 0:
            raise ValueError("future_signal_tolerance_seconds must be finite and non-negative")
        self.mandate = mandate
        self.broker = broker
        self.promotion_store = promotion_store
        self.arm = arm
        self.kill_switch = kill_switch or TradingKillSwitch()
        self.risk_engine = risk_engine or RiskEngine()
        self.sizer = sizer or FixedRiskSizer()
        self.journal = journal
        self.max_signal_age_seconds = float(max_signal_age_seconds)
        self.future_signal_tolerance_seconds = float(future_signal_tolerance_seconds)

    def execute(
        self,
        signal: TradeSignal,
        *,
        requested_quantity: int | None = None,
        now: datetime | None = None,
    ) -> LiveOrderResult:
        health = self.broker.health()
        if not health.ok:
            return self._reject(signal, f"broker unhealthy: {health.reason}")

        snapshot = self.broker.risk_snapshot({signal.symbol: signal.price})
        current_quantity = snapshot.position_quantity(signal.symbol)
        reducing = self._is_pure_reducing(signal.side, requested_quantity, current_quantity)

        if not reducing:
            freshness_error = self._signal_freshness_error(signal, now=now)
            if freshness_error is not None:
                if not self.kill_switch.active:
                    self.kill_switch.activate(freshness_error)
                return self._reject(signal, freshness_error)
            if self.mandate.mode != TradingMode.LIVE_AUTONOMOUS:
                return self._reject(signal, "live autonomous mode is not enabled")
            if not self.arm.is_armed_for(self.mandate):
                return self._reject(signal, "live autonomous session is not armed for this mandate")
            if self.kill_switch.active:
                return self._reject(signal, f"kill switch active: {self.kill_switch.reason}")
            if self.promotion_store.stage(signal.strategy_id) != StrategyStage.LIVE_ELIGIBLE:
                return self._reject(signal, "strategy is not live eligible")

        quantity = requested_quantity
        if quantity is None:
            quantity = abs(current_quantity) if reducing else self.sizer.size(signal, self.mandate, snapshot)
        if quantity is None or quantity <= 0:
            return self._reject(signal, "no admissible live quantity")

        reducing = self._is_pure_reducing(signal.side, quantity, current_quantity)
        if self.kill_switch.active and not reducing:
            return self._reject(signal, f"kill switch active: {self.kill_switch.reason}")

        decision = self.risk_engine.evaluate(signal, quantity, self.mandate, snapshot)
        if not decision.approved:
            return self._reject(signal, decision.reason)

        request = LiveOrderRequest(
            client_order_id=uuid4().hex,
            symbol=signal.symbol,
            side=signal.side,
            quantity=decision.approved_quantity,
            reference_price=signal.price,
            strategy_id=signal.strategy_id,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
        )
        result = self.broker.submit_order(request)
        self._record(
            "live_order",
            "accepted" if result.accepted else "rejected",
            {
                "broker": self.broker.name,
                "request": request,
                "result": result,
                "risk_reason": decision.reason,
                "risk_reducing": reducing,
                "signal_generated_at_utc": signal.generated_at_utc,
            },
            signal,
        )
        return result

    def _signal_freshness_error(self, signal: TradeSignal, *, now: datetime | None) -> str | None:
        if signal.generated_at_utc is None:
            return "live entry blocked: signal timestamp is missing"
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None or current.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        age = (
            current.astimezone(timezone.utc) - signal.generated_at_utc.astimezone(timezone.utc)
        ).total_seconds()
        if age < -self.future_signal_tolerance_seconds:
            return "live entry blocked: signal timestamp is unexpectedly in the future"
        if age > self.max_signal_age_seconds:
            return "live entry blocked: signal is stale"
        return None

    def _reject(self, signal: TradeSignal, reason: str) -> LiveOrderResult:
        result = LiveOrderResult(False, None, "rejected", 0, None, reason)
        self._record(
            "live_order",
            "rejected",
            {"broker": self.broker.name, "reason": reason},
            signal,
        )
        return result

    def _record(self, event_type: str, status: str, payload: object, signal: TradeSignal) -> None:
        if self.journal is None:
            return
        self.journal.record(
            event_type,
            status,
            payload,
            symbol=signal.symbol,
            strategy_id=signal.strategy_id,
        )

    @staticmethod
    def _is_pure_reducing(
        side: TradeSide,
        requested_quantity: int | None,
        current_quantity: int,
    ) -> bool:
        if current_quantity == 0:
            return False
        maximum = abs(current_quantity)
        quantity = maximum if requested_quantity is None else requested_quantity
        if quantity <= 0 or quantity > maximum:
            return False
        return (current_quantity > 0 and side == TradeSide.SELL) or (
            current_quantity < 0 and side == TradeSide.BUY
        )
