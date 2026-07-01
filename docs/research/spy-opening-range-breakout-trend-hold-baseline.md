# SPY Opening Range Breakout Trend Hold Baseline

This note records the first clean baseline cycle for
`spy-opening-range-breakout-trend-hold`.

The intent is to test whether simple SPY 5-minute opening-range breakouts can
capture larger trend-day moves than the rejected VWAP strategy family without
adding many filters at once.

## Baseline Rules

- instrument: `SPY`
- timeframe: `5Min`
- session: `XNYS regular`
- no premarket or postmarket bars
- quantity: `1`
- no trades before `10:00` New York
- no new entries after `14:30` New York
- force flat into the final regular-session bar
- signal model: breakout confirmed on completed bar close, entry simulated at
  the next bar open
- max trades per day tested separately at `1` and `2`
- stop variants tested separately:
  - opening-range midpoint
  - opening-range opposite side

## Cost Model

Primary baseline:

- `1` bp one-way slippage
- `$0.005/share`
- no minimum commission

Stress scenarios also run:

- `2` bps one-way slippage
- `3` bps one-way slippage
- `ibkr_ca_fixed_1bps`
- `ibkr_ca_tiered_1bps`

## One-Year Baseline Results

Window used from the local SPY cache:

- `2025-06-30` through `2026-06-27`

### ORB Midpoint Stop, Max 1 Trade

- `strategy_name`: `spy-opening-range-breakout-trend-hold`
- `variant_name`: `orb-midpoint-stop-max-1`
- `trades`: `246`
- `long_trades`: `137`
- `short_trades`: `109`
- `gross_pnl`: `$70.6463`
- `costed_pnl`: `$34.77425212`
- `profit_factor`: `1.1468`
- `expectancy_per_trade`: `$0.14136`
- `win_rate`: `39.84%`
- `average_win`: `$2.77198`
- `average_loss`: `-$1.60054`
- `max_drawdown`: `-$34.43425821`
- `worst_rolling_3_month`: `-$23.53392571`
- `worst_rolling_6_month`: `-$12.02521236`
- `largest_trade_pct_of_total_pnl`: `45.66%`
- `top_5_absolute_trades_pct_of_total_pnl`: `154.12%`
- `long_pnl`: `$12.727042145`
- `short_pnl`: `$22.047209975`
- `long_pf`: `1.1066`
- `short_pf`: `1.1876`
- `long_expectancy`: `$0.09290`
- `short_expectancy`: `$0.20227`

Stress:

- `2 bps`: `$3.82220424`, PF `1.0150`
- `3 bps`: `-$29.58984364`, PF `0.8928`
- `ibkr_ca_fixed_1bps`: `-$454.76574788`
- `ibkr_ca_tiered_1bps`: `-$134.96574788`

### ORB Midpoint Stop, Max 2 Trades

- `variant_name`: `orb-midpoint-stop-max-2`
- `trades`: `351`
- `costed_pnl`: `-$11.320183895`
- `profit_factor`: `0.9672`
- `expectancy_per_trade`: `-$0.03225`
- `max_drawdown`: `-$45.13261845`

### ORB Opposite Stop, Max 1 Trade

- `variant_name`: `orb-opposite-stop-max-1`
- `trades`: `246`
- `costed_pnl`: `-$8.06995886`
- `profit_factor`: `0.9725`
- `expectancy_per_trade`: `-$0.03280`
- `max_drawdown`: `-$40.37218033`

### ORB Opposite Stop, Max 2 Trades

- `variant_name`: `orb-opposite-stop-max-2`
- `trades`: `311`
- `costed_pnl`: `-$0.31939121`
- `profit_factor`: `0.9991`
- `expectancy_per_trade`: `-$0.00103`
- `max_drawdown`: `-$43.16370318`

## Baseline Verdict

The clean ORB baseline produced one promising starting point:

- `orb-midpoint-stop-max-1` is the only baseline variant clearly positive under
  the requested no-minimum cost model.

The baseline also shows important weaknesses:

- the edge is fragile and nearly disappears by `2` bps slippage
- it fails at `3` bps
- it fails both IBKR Canada minimum-commission approximations at quantity `1`
- PnL concentration is still high, with the largest trade worth `45.66%` of
  final costed PnL and the top 5 absolute trades worth `154.12%`

## Next Research Direction

Do not aggressively optimize. The next step should be one disciplined variant
at a time off the best baseline:

- keep `orb-midpoint-stop-max-1` as the baseline branch
- test one hold-improvement idea next, such as a structure or trailing-stop
  variant that tries to preserve large winners without adding multiple filters
  at once

This baseline is research-only. It is not live-ready and not yet a paper-trade
approval candidate.
