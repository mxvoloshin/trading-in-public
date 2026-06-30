# SPY VWAP Long/Short Strategy Research Cycle Summary

Repository: `mxvoloshin/trading-in-public`  
Plan file: `docs/research/spy-vwap-long-short-strategy-issue-plan.md`  
Instrument: SPY  
Bar size: 5-minute regular-session bars  
Local data window: 2025-06-30 through 2026-06-26  
Normalized position size: quantity 1  
Decision cost model: 1 bp one-way slippage + `$0.005/share`, no minimum commission

## Executive Decision

The long/short VWAP trend-continuation family is rejected for now. The clean baseline is negative after costs, and most filters improved the result only by removing trades or reducing damage. None created a robust trend-continuation edge.

The only candidate worth carrying forward is the separate VWAP range-reversion playbook, specifically `spy-vwap-range-reversion-1-5atr-band`.

This is not approved for paper or live trading yet because the expanded-history validation item is blocked. Local data covers roughly one year only, while the plan requires at least five years before any acceptance decision.

## Best Candidate

| Candidate | Trades | Long | Short | Costed PnL | PF | Exp/Trade | Max DD | Worst 6mo | Top Trade % | Top 5 Abs % | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `spy-vwap-range-reversion-1-5atr-band` | 111 | 50 | 61 | `$24.8321` | `10.8307` | `$0.2237` | `-$0.2858` | `$1.2210` | `9.72%` | `35.47%` | Keep for expanded validation |

Cost-stress result:

| Scenario | Result |
|---|---|
| Gross | `$40.9584` |
| 1 bp + `$0.005/share`, no minimum | `$24.8321`, PF `10.8307` |
| 2 bps slippage-only stress | `$10.9258`, PF `2.2557` |
| 3 bps slippage-only stress | `-$4.0905`, PF `0.7742` |
| IBKR Canada fixed 1 bp approximation, quantity 1 | `-$196.0579` |
| IBKR Canada tiered 1 bp approximation, quantity 1 | `-$51.7579` |

## Filter Comparison

| Plan Item | Variant / Filter | What It Tested | Trades | Long | Short | Costed PnL | PF | Exp/Trade | Max DD | Verdict | Effect on Strategy |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 000 | Base L/S trend continuation | Clean directional VWAP continuation baseline | 108 | 53 | 55 | `-$26.8453` | `0.6378` | `-$0.2486` | `-$26.8453` | Reject | Establishes a negative costed baseline. Longs are roughly flat; shorts are the main drag. |
| 001 | Daily trend context | Trade long only in bullish daily context and short only in bearish daily context | 38 | 31 | 7 | `-$0.0444` | `0.9980` | `-$0.0012` | `-$7.5418` | Diagnostic-only | Removes most damage but collapses the sample and remains slightly negative. |
| 002 | Opening drive quality | Require first-30-minute direction and close-location alignment | 65 | 34 | 31 | `-$1.6757` | `0.9570` | `-$0.0258` | `-$10.1259` | Diagnostic-only | Improves baseline and shows long bullish openings are promising, but short continuation remains weak. |
| 003 | RVOL buckets | Test loose, active, and normal-to-active first-30-minute RVOL gates | 79 | n/a | n/a | `-$30.6669` | `0.4856` | `-$0.3882` | `-$30.6669` | Reject | RVOL as a hard gate made results worse; keep only as reporting context. |
| 004 | ATR-normalized VWAP distance | Replace fixed VWAP distance with `<= 1.00 ATR` distance cap | 77 | 35 | 42 | `-$24.3819` | `0.5098` | `-$0.3166` | `-$27.4224` | Diagnostic-only | Removes some bad trades but remains below trade-count threshold and worse than base expectancy. |
| 005 | Signal-bar quality | Require better signal-bar close location and body quality | 54 | 52 | 2 | `-$1.8593` | `0.9365` | `-$0.0344` | `-$8.8546` | Diagnostic-only | Improves damage profile but becomes almost long-only and stays negative. |
| 006 | Signal-bar break entry | Enter only if next bar breaks the signal-bar high/low | 94 | 46 | 48 | `-$21.8989` | `0.6511` | `-$0.2330` | `-$24.3416` | Diagnostic-only | Slightly reduces loss but still fails after costs. Pairing with signal quality drops to 46 long-only trades. |
| 007 | VWAP/opening-range confluence | Require VWAP close to opening-range high/low in ATR terms | 17 | 17 | 0 | `$1.0952` | `1.1368` | `$0.0644` | `-$2.7084` | Diagnostic-only | Tight thresholds become positive but are too sparse and long-only. |
| 008 | R-based exits | Add initial stop and R targets at 1.0R, 1.5R, and 2.0R | 108 | 53 | 55 | `-$14.1312` | `0.6849` | `-$0.1308` | `-$14.7552` | Reject | 1.0R target reduces damage but remains materially negative. |
| 009 | Time stop | Exit stalled trades after broad bars-held / R-progress rules | 108 | 53 | 55 | `-$14.7227` | `0.6316` | `-$0.1363` | `-$15.7425` | Reject | Reduces damage in some combinations but does not create an edge. |
| 010 | Regime reporting | Add entry-time and full-session diagnostic regime labels | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Diagnostic-only | Shows bullish trend-continuation candidates are positive, while bearish trend-continuation candidates are heavily negative. |
| 011 | Range reversion 1.0 ATR band | Separate VWAP mean-reversion playbook with 1.0 ATR bands | 169 | n/a | n/a | `$0.8790` | `1.0300` | `$0.0052` | `-$6.6481` | Diagnostic-only | Slightly positive but too thin after costs to select. |
| 011 | Range reversion 1.5 ATR band | Separate VWAP mean-reversion playbook with 1.5 ATR bands | 111 | 50 | 61 | `$24.8321` | `10.8307` | `$0.2237` | `-$0.2858` | Keep for validation | First materially positive candidate with acceptable one-year trade count and low concentration. |
| 012 | Expanded validation | Rerun candidates over at least five years with yearly and OOS splits | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Blocked | Local cache only covers 2025-06-30 through 2026-06-26; Alpaca credentials were unavailable. |
| 013 | Cost stress | Apply gross, 1 bp, 2 bps, 3 bps, and IBKR-style cost scenarios | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Diagnostic gate | Range-reversion 1.5 ATR passes 2 bps no-minimum stress but fails 3 bps and quantity-1 IBKR Canada minimum approximations. |
| 014 | Final decision | Stop the cycle and decide next action | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Pause and validate | Do not add more filters until expanded-history validation is available. |

## Main Findings

1. Trend continuation is not currently viable.
   - The clean long/short base loses `-$26.8453` after costs.
   - Short trend-continuation trades are the main structural problem.
   - Most filters reduce losses by shrinking the sample, not by creating a robust edge.

2. Some diagnostics are still useful.
   - Daily trend state reduces damage but is too sparse as a hard filter.
   - Opening-drive buckets show bullish opening-drive longs are promising.
   - Entry-time regime labels show bullish trend candidates are positive while bearish trend candidates are strongly negative.
   - VWAP/opening-range confluence has a positive narrow pocket, but the sample is too small.

3. Range reversion deserves the next validation pass.
   - The 1.5 ATR range-reversion band has 111 one-year trades.
   - Both long and short sides are positive.
   - Concentration is acceptable under the no-minimum comparison model.
   - The result still needs expanded-history and execution-assumption validation.

4. Cost assumptions matter.
   - The best candidate survives the plan's 2 bps no-minimum stress gate.
   - It fails 3 bps slippage.
   - It also fails small-account IBKR Canada quantity-1 minimum-commission approximations.
   - Any next pass should test realistic sizing and commission assumptions alongside the normalized quantity-1 comparison.

## Acceptance Criteria Check

| Criterion | Status | Notes |
|---|---|---|
| Tested on at least 5 years of data | Fail / blocked | Local data is roughly one year only. |
| Average trades/year >= 100 | Pass for candidate | Range-reversion 1.5 ATR has 111 trades in the available year. |
| Total trades >= 500 preferred | Fail / blocked | Requires expanded history. |
| Positive costed expectancy | Pass for candidate | `$0.2237/trade` under no-minimum comparison costs. |
| Base-cost PF >= 1.10 | Pass for candidate | PF `10.8307`. |
| 2 bp slippage stress PF >= 1.05 | Pass for candidate | PF `2.2557` in the 2 bps no-minimum stress. |
| No single trade > 30% of total PnL | Pass for candidate | Top trade is `9.72%`. |
| Top 5 absolute trades <= 100% of total PnL | Pass for candidate | Top 5 absolute trades are `35.47%`. |
| No catastrophic rolling 6-month window | Pass in available year | Worst 6mo is positive for the selected candidate. |
| Long and short performance understood separately | Pass for available year | Long side `$6.6051`; short side `$18.2270`. |
| No future-looking labels used for entry | Pass | Full-session labels are diagnostic-only. |
| Works out-of-sample without retuning | Unknown | Blocked until expanded data exists. |

## Next Validation Work

1. Expand SPY 5-minute regular-session data to at least five years.
2. Rerun `spy-vwap-range-reversion-1-5atr-band` without retuning.
3. Produce year-by-year, in-sample, out-of-sample, and rolling-window summaries.
4. Recheck cost stress under no-minimum and realistic IBKR Canada sizing assumptions.
5. Review same-bar target/stop fill assumptions before any paper-trading decision.

## Final Recommendation

Pause trend-continuation filter development.

Validate `spy-vwap-range-reversion-1-5atr-band` on expanded history before adding more filters or considering paper trading.
