# SPY ORB Baseline Note

## Baseline

- family: `spy-opening-range-breakout-trend-hold`
- working variant: `orb-midpoint-stop-max-1`
- runnable strategy:
  `spy-opening-range-breakout-trend-hold-midpoint-stop-max-1`
- instrument: `SPY`
- timeframe: `5Min`
- market: `XNYS`
- session: `regular`
- quantity: `1`

## Exact Rules

- no premarket or postmarket bars
- no trades before `10:00` New York time
- no new entries after `14:30` New York time
- force flat into the final regular-session bar
- breakout is confirmed on a completed bar close
- approved market intents fill at the next bar open
- use the opening-range midpoint as the stop
- max trades per day: `1`

## Cost Model

Primary run:

- `1` bp one-way slippage
- `$0.005/share`
- no minimum commission

Stress runs:

- `2` bps one-way slippage
- `3` bps one-way slippage
- `ibkr_ca_fixed_1bps`
- `ibkr_ca_tiered_1bps`

## Canonical Artifacts

- summary:
  `.data/backtests/minimal/spy-opening-range-breakout-trend-hold-midpoint-stop-max-1/SPY.US_5Min_20250630T040000Z_20260628T040000Z.json`
- cost stress:
  `.data/backtests/cost-stress/spy-opening-range-breakout-trend-hold-midpoint-stop-max-1/SPY.US_5Min_20250630T040000Z_20260628T040000Z.json`

## Result

Status: completed
Decision: keep

Summary:
- Window: `2025-06-30` through `2026-06-27`
- Strategy name: `spy-opening-range-breakout-trend-hold`
- Variant name: `orb-midpoint-stop-max-1`
- Trades: `246`
- Long trades: `137`
- Short trades: `109`
- Gross PnL: `$70.6463`
- Costed PnL: `$34.77425212`
- Profit factor: `1.1468`
- Expectancy: `$0.14136`
- Max DD: `-$34.43425821`
- Worst 3mo: `-$23.53392571`
- Worst 6mo: `-$12.02521236`
- Largest trade pct of total PnL: `45.66%`
- Top 5 absolute trades pct of total PnL: `154.12%`
- Long PnL: `$12.727042145`
- Short PnL: `$22.047209975`
- Long PF: `1.1066`
- Short PF: `1.1876`
- Long expectancy: `$0.09290`
- Short expectancy: `$0.20227`
- 2 bps stress: `$3.82220424`, PF `1.0150`
- 3 bps stress: `-$29.58984364`, PF `0.8928`
- Notes: this is the only tested baseline variant that is clearly positive under
  the base no-minimum cost model on this window
- Next action: test one additional idea at a time off this baseline

## Baseline Comparison

Other tested baseline configurations on the same branch:

| Variant | Trades | Costed PnL | PF | Expectancy | Max DD | Verdict |
|---|---:|---:|---:|---:|---:|---|
| `orb-midpoint-stop-max-1` | 246 | `$34.7743` | `1.1468` | `$0.14136` | `-$34.4343` | keep |
| `orb-midpoint-stop-max-2` | 351 | `-$11.3202` | `0.9672` | `-$0.03225` | `-$45.1326` | reject |
| `orb-opposite-stop-max-1` | 246 | `-$8.0700` | `0.9725` | `-$0.03280` | `-$40.3722` | reject |
| `orb-opposite-stop-max-2` | 311 | `-$0.3194` | `0.9991` | `-$0.00103` | `-$43.1637` | reject |
