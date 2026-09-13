# Strategy R&D v0.2 Research Protocol

Status: research only

## Objective

Improve out-of-sample consistency without weakening NEXA's existing promotion gates or retroactively changing the validated v0.1 checkpoint.

## Frozen baseline evidence

- `adaptive_router_v1` remains research only.
- `adaptive_momentum_v1` primary 756/252/252 walk-forward result: 8/14 positive windows, 61 trades, net PnL 2588.29; fails positive-window robustness gate.
- `mean_reversion_v1` is not a viable lead candidate: 2/14 positive windows, 8 trades, net PnL -271.73, multiple promotion-gate failures.
- `adaptive_momentum_v2` ATR-normalized breakout filter is rejected: 8/14 positive windows, 49 trades, net PnL 1862.09. It reduced activity and PnL without improving window robustness.
- `adaptive_momentum_v3` strong-close breakout filter is rejected: 7/14 positive windows, 49 trades, net PnL 1099.10, aggregate PF 1.199. It materially worsened robustness and economics versus v1.

These results are known evidence and must not be treated as unseen holdout evidence later.

## Data contamination / holdout rule

The historical NIFTYBEES series, the older 2009-2016 regime, and the recent 2025-10-29 through 2026-08-20 period have already been inspected. They are therefore not pristine holdouts.

No future candidate may be described as validated on unseen historical data unless a genuinely untouched dataset is introduced and its boundary is declared before results are inspected. Future live or paper-forward data can become new out-of-sample evidence if its rules are fixed before collection.

## Candidate discipline

1. Every material strategy change gets a new strategy ID.
2. One economic hypothesis per candidate; avoid broad parameter sweeps.
3. Do not weaken promotion thresholds to make a candidate pass.
4. Do not cherry-pick walk-forward start dates or drop losing windows after seeing outcomes.
5. Keep transaction-cost and slippage assumptions fixed within a comparison and report them with results.
6. Rejected candidates remain documented; do not silently recycle them under a new ID.

## Fixed evaluation sequence

For each new candidate:

1. Run the full unit/regression suite.
2. Run the primary walk-forward configuration: 756 train / 252 test / 252 step.
3. If the primary result is not a clear improvement over v1 on robustness, reject the candidate and stop.
4. Only candidates that improve primary robustness proceed to the predefined robustness matrix:
   - 504 / 126 / 126
   - 756 / 126 / 126
   - 756 / 252 / 252
   - 1008 / 252 / 252
5. Treat overlapping/common-window identity explicitly; a pass caused only by dropping an earlier losing boundary window is not robustness evidence.
6. Report trade count, net PnL, profit factor, expectancy, max drawdown, and positive-window fraction for every configuration.

## Promotion rule

Backtest success alone does not authorize paper or live trading. A research candidate must first satisfy the existing research gates robustly, then advance through NEXA's paper-evidence and owner-approval controls. Live eligibility remains separate and fail-closed.

## Next hypothesis family

Do not continue adding ad-hoc breakout-strength filters to v1. V2 and V3 already tested two such filters and failed to improve robustness. The next candidate should be economically distinct from those filters, with its hypothesis written down before its results are inspected.
