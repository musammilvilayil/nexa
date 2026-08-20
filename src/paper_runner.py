from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path

from runtime import PROJECT_ROOT, build_runtime
from skills.trading import CSVMarketDataProvider, PaperRuntimeService


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run NEXA autonomous paper trading through the production safety gates.",
    )
    parser.add_argument(
        "--data-root",
        default=os.getenv("NEXA_MARKET_DATA_DIR", str(PROJECT_ROOT / "data" / "market")),
        help="Directory containing SYMBOL.csv market snapshots.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=float(os.getenv("NEXA_PAPER_POLL_SECONDS", "60")),
        help="Delay between bounded provider polls.",
    )
    parser.add_argument(
        "--cycles",
        type=int,
        default=1,
        help="Number of cycles to run. Use 0 for a long-running local service.",
    )
    return parser.parse_args()


def _print_cycle(cycle) -> None:
    payload = {
        "started_at_utc": cycle.started_at_utc.isoformat(),
        "finished_at_utc": cycle.finished_at_utc.isoformat(),
        "ok": cycle.ok,
        "symbols": [],
    }
    for item in cycle.symbols:
        row = {"symbol": item.symbol, "error": item.error}
        if item.result is not None:
            row.update(
                {
                    "status": item.result.status,
                    "reason": item.result.reason,
                    "order_id": item.result.order.order_id if item.result.order else None,
                }
            )
        payload["symbols"].append(row)
    print(json.dumps(payload, separators=(",", ":")))


def main() -> int:
    args = _parse_args()
    data_root = Path(args.data_root).expanduser().resolve()
    if not data_root.exists() or not data_root.is_dir():
        raise SystemExit(f"market data directory not found: {data_root}")
    if args.interval_seconds <= 0:
        raise SystemExit("--interval-seconds must be positive")
    if args.cycles < 0:
        raise SystemExit("--cycles cannot be negative")

    runtime = build_runtime()
    provider = CSVMarketDataProvider(data_root)
    service = PaperRuntimeService(
        runtime.trading_brain,
        provider,
        runtime.trading_brain.mandate.allowed_symbols,
    )

    # This is deliberately fail-closed. Research mode or an unpromoted strategy
    # cannot be converted into autonomous paper execution by this CLI.
    service.arm()

    def request_stop(*_args) -> None:
        service.stop()

    signal.signal(signal.SIGINT, request_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, request_stop)

    max_cycles = None if args.cycles == 0 else args.cycles
    try:
        completed = service.run(
            interval_seconds=args.interval_seconds,
            max_cycles=max_cycles,
            on_cycle=_print_cycle,
        )
    finally:
        service.stop()

    print(json.dumps({"status": "stopped", "completed_cycles": completed}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
