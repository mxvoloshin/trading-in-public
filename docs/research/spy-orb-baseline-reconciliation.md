# SPY ORB Midpoint Baseline Reconciliation

This note reconciles the apparent mismatch between the previously reported
`+$34.77` costed PnL baseline and the later `-$48.71` costed PnL run for
`spy-opening-range-breakout-trend-hold-midpoint-stop-max-1`.

## Verdict

The baseline did **not** regress.

The two results came from **different one-year windows**:

- old baseline window: `2025-06-30` through `2026-06-27`
- new run window: `2025-01-01` through `2025-12-31`

Re-running the old window from the cached data reproduces the prior profitable
result exactly:

- old window rerun: `costed_pnl = +34.774252120`
- new window run: `costed_pnl = -48.706825210`

The large swing is therefore a **sample-period effect**, not a strategy-code
change introduced by the diagnostics/exit-variant work.

## Sources Compared

Old summary source:

- [spy-opening-range-breakout-trend-hold-baseline.md](/Users/ghost/.openclaw/workspace/projects/public/trading-in-public/docs/research/spy-opening-range-breakout-trend-hold-baseline.md)
- reproduced old-window JSON:
  [SPY.US_5Min_20250630T040000Z_20260628T040000Z.json](/Users/ghost/.openclaw/workspace/projects/public/trading-in-public/.data/backtests/minimal/spy-opening-range-breakout-trend-hold-midpoint-stop-max-1/SPY.US_5Min_20250630T040000Z_20260628T040000Z.json)

New run source:

- [SPY.US_5Min_20250101T050000Z_20260101T050000Z.json](/Users/ghost/.openclaw/workspace/projects/public/trading-in-public/.data/backtests/minimal/spy-opening-range-breakout-trend-hold-midpoint-stop-max-1/SPY.US_5Min_20250101T050000Z_20260101T050000Z.json)

## Comparison

| Field | Old baseline | New run | Notes |
|---|---:|---:|---|
| Summary source | baseline note + reproduced JSON | new JSON | Old committed note was aggregate-only; rerun reproduced it exactly |
| Exact date range | `2025-06-30` to `2026-06-27` | `2025-01-01` to `2025-12-31` | Main cause of mismatch |
| Normalized session files | `250` | `250` | Old range resolves to `2025-06-30`..`2026-06-26`; new to `2025-01-02`..`2025-12-31` |
| Bars loaded | `19,500` | `19,500` | `250` regular sessions x `78` five-minute bars |
| Trade count | `246` | `248` | Same max-1-trade logic, different market window |
| Long trades | `137` | `135` | Window effect |
| Short trades | `109` | `113` | Window effect |
| Gross PnL | `+70.6463` | `-15.4966` | Window effect |
| Costed PnL | `+34.774252120` | `-48.706825210` | Window effect |
| Profit factor | `1.1468` | `0.8242` | Window effect |
| Max drawdown | `-34.434258210` | `-71.094595410` | Window effect |

## Strategy/Execution Model Check

These were the same between runs:

- Entry model:
  completed-bar close breakout signal, market intent filled at the **next bar
  open**
- Stop model:
  **opening-range midpoint**
- EOD flatten behavior:
  flatten at the **15:55 New York** bar
- Session model:
  **XNYS regular session only**
- Cost model:
  **1 bp one-way slippage** and **$0.005/share commission**, no minimum
- Price adjustment basis:
  **raw / unadjusted** Alpaca bars

Code references:

- Entry / flatten / midpoint stop:
  [spy_opening_range_breakout.py](/Users/ghost/.openclaw/workspace/projects/public/trading-in-public/packages/trade_strategies/src/trade_strategies/spy_opening_range_breakout.py:54)
- Entry time boundaries and flatten bar:
  [spy_opening_range_breakout.py](/Users/ghost/.openclaw/workspace/projects/public/trading-in-public/packages/trade_strategies/src/trade_strategies/spy_opening_range_breakout.py:64)
- Runner next-bar-open fill model:
  [backtest.py](/Users/ghost/.openclaw/workspace/projects/public/trading-in-public/apps/research/src/trade_research_app/backtest.py:1217)
- Cost model:
  [backtest.py](/Users/ghost/.openclaw/workspace/projects/public/trading-in-public/apps/research/src/trade_research_app/backtest.py:173)
- Raw Alpaca adjustment default:
  [alpaca.py](/Users/ghost/.openclaw/workspace/projects/public/trading-in-public/packages/trade_data/src/trade_data/alpaca.py:29)

## Why The New Window Is Worse

The `2025-01-01` to `2025-12-31` run includes a very weak first half:

- `2025-01`: `-15.71`
- `2025-04`: `-20.86`
- `2025-05`: `-20.66`
- `2025-06`: `-10.34`

The second half improves materially:

- `2025-07`: `+12.07`
- `2025-10`: `+14.35`
- `2025-12`: `+10.25`

That profile lines up with the old profitable window beginning on
`2025-06-30`, which captures the stronger later regime and excludes the weak
January through June 2025 stretch.

## First/Last 10 Trades

Not available from the preserved artifacts.

The saved backtest JSONs contain aggregate summaries and breakdowns, but they do
not persist a per-trade ledger. Because the original old run did not save trade
rows, a strict old-vs-new first/last-10 trade comparison cannot be recovered
from the committed/public-safe artifacts alone.

If needed, the next step is to add an optional trade-ledger export to the
backtest runner and re-run both windows so the sequence can be compared exactly.

## Conclusion

There is no evidence that the ORB midpoint baseline changed because of the new
diagnostics or exit-variant work.

The mismatch came from comparing:

- a profitable `2025-06-30` to `2026-06-27` window
- against a weaker `2025-01-01` to `2025-12-31` window

Those are different market regimes with the same strategy logic.
