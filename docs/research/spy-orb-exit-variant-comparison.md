# SPY ORB Exit-Only Variant Comparison

**Date:** 2025-07-01  
**Strategy family:** `spy-opening-range-breakout-trend-hold`  
**Baseline:** `orb-midpoint-stop-max-1` (midpoint stop or EOD)  
**Data:** SPY 5-min bars, 2025-01-01 → 2025-12-31, Alpaca  
**Cost model:** 1 bps slippage + $0.005/share commission (costed), unless noted  
**Entry logic:** identical across all variants — no entry filters, no opening range optimization, max 1 trade/day  

---

## Summary Table

| Metric | Baseline (midpoint) | Break-even +1R | ATR trail 1.0 | ATR trail 1.5 | ATR trail 2.0 | Structure trail +1R |
|---|---|---|---|---|---|---|
| **Trades** | 248 | 248 | 248 | 248 | 248 | 248 |
| **Long / Short** | 135 / 113 | 135 / 113 | 135 / 113 | 135 / 113 | 135 / 113 | 135 / 113 |
| **Gross PnL** | −$15.50 | −$29.19 | −$47.24 | −$32.61 | −$40.39 | −$32.89 |
| **Costed PnL** | −$48.71 | −$62.40 | −$80.45 | −$65.82 | −$73.60 | −$66.09 |
| **PF** | 0.82 | 0.71 | 0.46 | 0.61 | 0.61 | 0.68 |
| **Expectancy/trade** | −$0.196 | −$0.252 | −$0.324 | −$0.265 | −$0.297 | −$0.267 |
| **Win rate** | 34.3% | 25.0% | 32.3% | 38.3% | 41.9% | 48.4% |
| **Avg win** | $2.69 | $2.45 | $0.86 | $1.08 | $1.12 | $1.19 |
| **Avg loss** | −$1.70 | −$1.15 | −$0.89 | −$1.10 | −$1.32 | −$1.63 |
| **Max DD** | −$71.09 | −$74.64 | −$80.80 | −$65.95 | −$75.45 | −$67.63 |
| **Worst rolling 3-mo** | −$51.86 | −$40.26 | −$35.08 | −$34.82 | −$46.00 | −$35.77 |
| **Worst rolling 6-mo** | −$70.88 | −$61.16 | −$48.44 | −$46.62 | −$58.87 | −$49.13 |
| **Largest trade % PnL** | 32.6% | 15.1% | 16.6% | 24.7% | 27.6% | 14.2% |
| **Top 5 abs % PnL** | 100.1% | 61.3% | 36.8% | 52.0% | 58.6% | 44.5% |
| **Long PnL** | −$23.33 | −$25.37 | −$39.04 | −$34.05 | −$46.01 | −$37.50 |
| **Long PF** | 0.82 | 0.78 | 0.48 | 0.62 | 0.55 | 0.66 |
| **Long expectancy** | −$0.173 | −$0.188 | −$0.289 | −$0.252 | −$0.341 | −$0.278 |
| **Short PnL** | −$25.38 | −$37.04 | −$41.41 | −$31.77 | −$27.59 | −$28.59 |
| **Short PF** | 0.82 | 0.63 | 0.44 | 0.60 | 0.69 | 0.71 |
| **Short expectancy** | −$0.225 | −$0.328 | −$0.366 | −$0.281 | −$0.244 | −$0.253 |

## Cost Stress (slippage only)

| Scenario | Baseline | Break-even +1R | ATR 1.0 | ATR 1.5 | ATR 2.0 | Structure |
|---|---|---|---|---|---|---|
| **Gross** | −$15.50 | −$29.19 | −$47.24 | −$32.61 | −$40.39 | −$32.89 |
| **2 bps** | −$76.96 | −$90.65 | −$108.70 | −$94.07 | −$101.85 | −$94.34 |
| **3 bps** | −$107.69 | −$121.39 | −$139.43 | −$124.80 | −$132.58 | −$125.07 |

## MFE/MAE/R Diagnostics

| Metric | Baseline | Break-even +1R | ATR 1.0 | ATR 1.5 | ATR 2.0 | Structure |
|---|---|---|---|---|---|---|
| **Avg MFE** | $2.14 | $1.89 | $1.00 | $1.27 | $1.48 | $1.47 |
| **Avg MAE** | $1.62 | $1.38 | $0.99 | $1.08 | $1.16 | $1.34 |
| **Avg final R** | −0.046 | −0.096 | −0.174 | −0.139 | −0.124 | −0.147 |
| **Pct reached +1R** | 48.8% | 46.4% | 20.2% | 31.0% | 38.3% | 39.1% |
| **Pct +1R then negative** | 18.5% | 25.0% | 2.4% | 3.2% | 4.8% | 3.2% |

---

## Decision

**Decision rule:** Keep a variant only if it improves costed expectancy or drawdown without causing worse concentration or collapsing under 2 bps stress.

### Assessment

| Variant | Costed expectancy | Max DD | Concentration (top 5 %) | 2 bps stress | Verdict |
|---|---|---|---|---|---|
| **Baseline (midpoint)** | −$0.196 | −$71.09 | 100.1% | −$76.96 | **Control** |
| **Break-even +1R** | −$0.252 (worse) | −$74.64 (worse) | 61.3% (better) | −$90.65 (worse) | ❌ Reject |
| **ATR trail 1.0** | −$0.324 (worse) | −$80.80 (worse) | 36.8% (better) | −$108.70 (worse) | ❌ Reject |
| **ATR trail 1.5** | −$0.265 (worse) | −$65.95 (better) | 52.0% (better) | −$94.07 (worse) | ❌ Reject |
| **ATR trail 2.0** | −$0.297 (worse) | −$75.45 (worse) | 58.6% (better) | −$101.85 (worse) | ❌ Reject |
| **Structure trail +1R** | −$0.267 (worse) | −$67.63 (better) | 44.5% (better) | −$94.34 (worse) | ❌ Reject |

### Conclusion

**No exit variant improves on the baseline.** The midpoint-stop baseline has the best costed expectancy (−$0.196/trade) and the best 2 bps stress result (−$76.96). All trailing/break-even exits cut trades shorter, reducing gross PnL faster than they reduce costs, and none survive 2 bps stress better than the control.

Key observations from MFE/MAE/R diagnostics:
- **48.8% of baseline trades reach +1R**, but **18.5% of those close negative** — the midpoint stop gives back gains on nearly 1 in 5 trades that were ahead
- Break-even +1R exploits this by cutting losses early, but it also cuts winners: win rate drops from 34.3% to 25.0%, and avg win drops from $2.69 to $2.45
- ATR trail 1.0 has the tightest stops (avg holding 24 min vs 176 min baseline) — it exits too early, killing gross edge
- Structure trail has the best win rate (48.4%) but can't overcome the gross PnL deficit

**Next direction:** The baseline midpoint stop is the best exit for this ORB variant. The diagnostic data suggests the problem is **entry quality**, not exit management — 49% of trades never reach +1R. Focus should shift to entry filters (gap direction, opening drive quality, daily trend context) rather than further exit optimization.
