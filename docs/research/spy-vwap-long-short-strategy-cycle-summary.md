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

Update after stop validation: the earlier `spy-vwap-range-reversion-1-5atr-band` result was invalidated by a stop-placement bug. See `docs/research/spy-vwap-range-reversion-stop-validation.md`.

With the corrected stop logic, neither checked range-reversion variant remains viable after the base 1 bp + `$0.005/share` cost model. This is not approved for paper or live trading.

## Validation Outcome

| Candidate | Trades | Long | Short | Costed PnL | PF | Exp/Trade | Max DD | Worst 6mo | Top Trade % | Top 5 Abs % | Decision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `spy-vwap-range-reversion-base` | 154 | 72 | 82 | `-$24.8627` | `0.6701` | `-$0.1614` | `-$24.8876` | `-$16.9455` | `invalidated pre-fix` | `invalidated pre-fix` | Reject |
| `spy-vwap-range-reversion-1-5atr-band` | 91 | 42 | 49 | `-$9.5115` | `0.7920` | `-$0.1045` | `-$12.2999` | `-$11.4066` | `invalidated pre-fix` | `invalidated pre-fix` | Reject |

Cost-stress result:

| Scenario | Result |
|---|---|
| Range-reversion base, 1 bp + `$0.005/share`, no minimum | `-$24.8627`, PF `0.6701` |
| Range-reversion base, 2 bps slippage-only stress | `-$45.9548`, PF `0.4613` |
| Range-reversion base, 3 bps slippage-only stress | `-$72.8240`, PF `0.2821` |
| Range-reversion base, IBKR Canada fixed approximation | `-$331.3227`, PF `0.0085` |
| Range-reversion base, IBKR Canada tiered approximation | `-$131.1227`, PF `0.1304` |
| Range-reversion 1.5 ATR, 1 bp + `$0.005/share`, no minimum | `-$9.5115`, PF `0.7920` |
| Range-reversion 1.5 ATR, 2 bps slippage-only stress | `-$20.7669`, PF `0.6065` |
| Range-reversion 1.5 ATR, 3 bps slippage-only stress | `-$42.0164`, PF `0.3663` |
| Range-reversion 1.5 ATR, IBKR Canada fixed approximation | `-$190.6015`, PF `0.0146` |
| Range-reversion 1.5 ATR, IBKR Canada tiered approximation | `-$72.3015`, PF `0.2080` |

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
| 011 | Range reversion 1.0 ATR band | Separate VWAP mean-reversion playbook with 1.0 ATR bands | 154 | 72 | 82 | `-$24.8627` | `0.6701` | `-$0.1614` | `-$24.8876` | Reject | After stop-fix rerun, the corrected result is negative after costs and fails stress checks. |
| 011 | Range reversion 1.5 ATR band | Separate VWAP mean-reversion playbook with 1.5 ATR bands | 91 | 42 | 49 | `-$9.5115` | `0.7920` | `-$0.1045` | `-$12.2999` | Reject | The prior positive result was invalidated by a stop-placement bug; the corrected rerun is negative after costs and fails 2 bps stress. |
| 012 | Expanded validation | Rerun candidates over at least five years with yearly and OOS splits | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Blocked | Local cache only covers 2025-06-30 through 2026-06-26; Alpaca credentials were unavailable. |
| 013 | Cost stress | Apply gross, 1 bp, 2 bps, 3 bps, and IBKR-style cost scenarios | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Reject gate | Both corrected range-reversion variants fail the 1 bp base-cost test, fail 2 bps stress, fail 3 bps stress, and fail quantity-1 IBKR Canada approximations. |
| 014 | Final decision | Stop the cycle and decide next action | n/a | n/a | n/a | n/a | n/a | n/a | n/a | Stop and pivot | Reject the current SPY VWAP strategy family and do not add more filters unless a new thesis is defined. |

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

3. Range reversion no longer qualifies as the next validation pass.
   - The prior `1.5 ATR` headline result was invalidated by a stop-placement bug.
   - With corrected stop logic, both checked range-reversion variants are negative after 1 bp + commission costs.
   - The fixed `1.5 ATR` variant also fails the 2 bps stress gate.

4. Cost assumptions matter.
   - Neither corrected range-reversion variant survives the base cost model.
   - Both degrade further under 2 bps and 3 bps slippage.
   - Both also fail small-account IBKR Canada quantity-1 minimum-commission approximations.

## Acceptance Criteria Check

| Criterion | Status | Notes |
|---|---|---|
| Tested on at least 5 years of data | Fail / blocked | Local data is roughly one year only. |
| Average trades/year >= 100 | Fail for corrected lead | Corrected 1.5 ATR variant has 91 trades; corrected base has 154 trades but is negative after costs. |
| Total trades >= 500 preferred | Fail / blocked | Requires expanded history. |
| Positive costed expectancy | Fail | Corrected range-reversion base `-$0.1614/trade`; corrected 1.5 ATR `-$0.1045/trade`. |
| Base-cost PF >= 1.10 | Fail | Corrected range-reversion base PF `0.6701`; corrected 1.5 ATR PF `0.7920`. |
| 2 bp slippage stress PF >= 1.05 | Fail | Corrected range-reversion base PF `0.4613`; corrected 1.5 ATR PF `0.6065`. |
| No single trade > 30% of total PnL | Not meaningful for rejected result | Pre-fix concentration figures were invalidated by the stop-placement bug. |
| Top 5 absolute trades <= 100% of total PnL | Not meaningful for rejected result | Pre-fix concentration figures were invalidated by the stop-placement bug. |
| No catastrophic rolling 6-month window | Fail | Corrected range-reversion base and corrected 1.5 ATR both have strongly negative worst 6-month windows. |
| Long and short performance understood separately | Pass for available year | Corrected 1.5 ATR long `-$7.9674`; short `-$1.5441`. |
| No future-looking labels used for entry | Pass | Full-session labels are diagnostic-only. |
| Works out-of-sample without retuning | Unknown | Blocked until expanded data exists. |

## Next Validation Work

1. Expand SPY 5-minute regular-session data to at least five years.
2. If range reversion is revisited later, start only from the corrected stop logic.
3. Produce new hypotheses instead of trusting the invalidated pre-fix winner.
4. Recheck cost stress under no-minimum and realistic IBKR Canada sizing assumptions for any future candidate.
5. Keep the stop-validation note linked in future research writeups so the invalidated result does not get reused.

## Final Recommendation

Pause trend-continuation filter development.

Reject the current range-reversion candidates. The prior `spy-vwap-range-reversion-1-5atr-band` result was invalidated by a stop-placement bug, and the corrected rerun is negative after 1 bp costs and fails 2 bps stress.
