from __future__ import annotations

import math

from .models import RiskSnapshot, TradeSignal, TradingMandate


class FixedRiskSizer:
    """Sizes a trade from the owner's hard risk and notional limits.

    Returning zero means there is no admissible quantity. The sizer never rounds
    upward, so integer sizing cannot exceed configured limits through rounding.
    """

    def size(
        self,
        signal: TradeSignal,
        mandate: TradingMandate,
        snapshot: RiskSnapshot,
    ) -> int:
        if signal.stop_loss is None:
            return 0

        risk_per_unit = abs(signal.price - signal.stop_loss)
        if not math.isfinite(risk_per_unit) or risk_per_unit <= 0:
            return 0

        by_risk = int(mandate.max_risk_per_trade // risk_per_unit)
        by_notional = int(mandate.max_notional_per_trade // signal.price)
        remaining_exposure = max(0.0, mandate.max_total_exposure - snapshot.total_exposure)
        by_exposure = int(remaining_exposure // signal.price)
        return max(0, min(by_risk, by_notional, by_exposure))
