from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Protocol

from .market import Candle, MarketSeries


class MarketDataProvider(Protocol):
    def load(self, symbol: str) -> MarketSeries:
        ...


class CSVMarketDataProvider:
    """Sandboxed historical CSV loader for local research.

    Files are resolved under one configured data root; absolute paths and parent
    traversal are not accepted. Expected columns are timestamp, open, high, low,
    close, and optional volume. Timestamps must include a timezone offset or Z.
    """

    REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close")

    def __init__(
        self,
        data_root: str | Path,
        *,
        max_file_bytes: int = 100_000_000,
    ) -> None:
        root = Path(data_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError("market data root must be an existing directory")
        if max_file_bytes <= 0:
            raise ValueError("max_file_bytes must be positive")
        self.data_root = root
        self.max_file_bytes = int(max_file_bytes)

    def load(self, symbol: str) -> MarketSeries:
        key = symbol.strip().upper()
        if not key or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in key):
            raise ValueError("invalid symbol")
        return self.load_file(f"{key}.csv", symbol=key)

    def load_file(self, relative_path: str | Path, *, symbol: str | None = None) -> MarketSeries:
        relative = Path(relative_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("market data path must be relative and contained")
        target = (self.data_root / relative).resolve()
        if not target.is_relative_to(self.data_root):
            raise ValueError("market data path escaped configured root")
        if target.suffix.lower() != ".csv":
            raise ValueError("market data file must be CSV")
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(target)
        if target.stat().st_size > self.max_file_bytes:
            raise ValueError("market data file exceeds size limit")

        candles: list[Candle] = []
        with target.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = tuple(reader.fieldnames or ())
            missing = [name for name in self.REQUIRED_COLUMNS if name not in fields]
            if missing:
                raise ValueError(f"market CSV missing columns: {', '.join(missing)}")
            for line_number, row in enumerate(reader, start=2):
                try:
                    timestamp = _parse_timestamp(row["timestamp"])
                    candles.append(
                        Candle(
                            timestamp=timestamp,
                            open=float(row["open"]),
                            high=float(row["high"]),
                            low=float(row["low"]),
                            close=float(row["close"]),
                            volume=float(row.get("volume") or 0.0),
                        )
                    )
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"invalid market CSV row {line_number}: {exc}") from exc

        resolved_symbol = (symbol or target.stem).strip().upper()
        return MarketSeries(resolved_symbol, tuple(candles))


def _parse_timestamp(value: str) -> datetime:
    text = str(value).strip()
    if not text:
        raise ValueError("timestamp required")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include timezone information")
    return parsed
