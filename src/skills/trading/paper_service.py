from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Event
from typing import Callable

from .brain import TradingBrain
from .data_provider import MarketDataProvider
from .runtime import PaperCycleResult


@dataclass(frozen=True)
class PaperSymbolCycle:
    symbol: str
    result: PaperCycleResult | None
    error: str | None = None


@dataclass(frozen=True)
class PaperServiceCycle:
    started_at_utc: datetime
    finished_at_utc: datetime
    symbols: tuple[PaperSymbolCycle, ...]

    @property
    def ok(self) -> bool:
        return all(item.error is None for item in self.symbols)


class PaperRuntimeService:
    """Bounded service loop around the autonomous paper trader.

    The service owns scheduling and market-data polling only. Strategy promotion,
    mandate checks, sizing, and order approval remain inside ``TradingBrain`` and
    ``RiskEngine``. A provider failure is isolated to that symbol and is reported
    as an error rather than converted into a synthetic market update.
    """

    def __init__(
        self,
        brain: TradingBrain,
        provider: MarketDataProvider,
        symbols: tuple[str, ...],
    ) -> None:
        normalized = tuple(dict.fromkeys(symbol.strip().upper() for symbol in symbols if symbol.strip()))
        if not normalized:
            raise ValueError("paper service requires at least one symbol")
        disallowed = tuple(symbol for symbol in normalized if symbol not in brain.mandate.allowed_symbols)
        if disallowed:
            raise PermissionError(f"symbols outside trading mandate: {', '.join(disallowed)}")

        self.brain = brain
        self.provider = provider
        self.symbols = normalized
        self._stop = Event()

    def arm(self) -> None:
        """Arm paper execution through the existing promotion and mandate gates."""

        self.brain.arm_paper_runtime()

    def stop(self) -> None:
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def run_cycle(self) -> PaperServiceCycle:
        started = datetime.now(timezone.utc)
        results: list[PaperSymbolCycle] = []

        for symbol in self.symbols:
            if self._stop.is_set():
                break
            try:
                series = self.provider.load(symbol)
                result = self.brain.on_market_update(series)
                results.append(PaperSymbolCycle(symbol=symbol, result=result))
            except Exception as exc:
                results.append(
                    PaperSymbolCycle(
                        symbol=symbol,
                        result=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )

        return PaperServiceCycle(
            started_at_utc=started,
            finished_at_utc=datetime.now(timezone.utc),
            symbols=tuple(results),
        )

    def run(
        self,
        *,
        interval_seconds: float,
        max_cycles: int | None = None,
        on_cycle: Callable[[PaperServiceCycle], None] | None = None,
    ) -> int:
        """Run until stopped or the optional cycle budget is exhausted.

        ``max_cycles`` provides a hard execution bound for supervised jobs and
        tests. Passing ``None`` allows a long-running local service, which can be
        stopped through ``stop()`` or Ctrl+C in the CLI wrapper.
        """

        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if max_cycles is not None and max_cycles <= 0:
            raise ValueError("max_cycles must be positive when provided")

        completed = 0
        while not self._stop.is_set() and (max_cycles is None or completed < max_cycles):
            cycle = self.run_cycle()
            completed += 1
            if on_cycle is not None:
                on_cycle(cycle)

            if self._stop.is_set() or (max_cycles is not None and completed >= max_cycles):
                break
            self._stop.wait(interval_seconds)

        return completed
