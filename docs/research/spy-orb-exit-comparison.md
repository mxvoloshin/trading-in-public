# SPY ORB Exit Comparison Note

## Question

Do exit-only variants improve the ORB branch versus the midpoint-stop baseline?

## Baseline Used

- family: `spy-opening-range-breakout-trend-hold`
- control variant: `orb-midpoint-stop-max-1`
- window: `2025-01-01` through `2025-12-31`
- cost model: `1` bp one-way slippage + `$0.005/share`

## Canonical Artifacts

- control summary:
  `.data/backtests/minimal/spy-opening-range-breakout-trend-hold-midpoint-stop-max-1/SPY.US_5Min_20250101T050000Z_20260101T050000Z.json`
- comparison summaries:
  `.data/backtests/minimal/spy-opening-range-breakout-trend-hold-breakeven-after-1r-max-1/SPY.US_5Min_20250101T050000Z_20260101T050000Z.json`
  `.data/backtests/minimal/spy-opening-range-breakout-trend-hold-atr-trail-1-0-max-1/SPY.US_5Min_20250101T050000Z_20260101T050000Z.json`
  `.data/backtests/minimal/spy-opening-range-breakout-trend-hold-atr-trail-1-5-max-1/SPY.US_5Min_20250101T050000Z_20260101T050000Z.json`
  `.data/backtests/minimal/spy-opening-range-breakout-trend-hold-atr-trail-2-0-max-1/SPY.US_5Min_20250101T050000Z_20260101T050000Z.json`
  `.data/backtests/minimal/spy-opening-range-breakout-trend-hold-structure-trail-after-1r-max-1/SPY.US_5Min_20250101T050000Z_20260101T050000Z.json`

## Result

Status: completed
Decision: reject

Summary:
- Window: `2025-01-01` through `2025-12-31`
- What was tested: exit-only changes with identical entry logic
- What passed: none of the tested exit variants improved costed expectancy
- What failed: all variants remained negative after costs and degraded further
  under 2 bps and 3 bps stress
- What remains unknown: whether entry filters can materially improve the branch
- Next action: stop exit-only variation and shift to entry-quality questions

## Comparison Table

| Variant | Trades | Costed PnL | PF | Expectancy | Max DD | Worst 3mo | Worst 6mo | Largest Trade % | Top 5 Abs % | 2 bps | 3 bps | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| `orb-midpoint-stop-max-1` | 248 | `-$48.7068` | `0.8242` | `-$0.1964` | `-$71.0946` | `-$51.8636` | `-$70.8800` | `32.60%` | `100.07%` | `-$76.9571` | `-$107.6873` | control |
| `orb-breakeven-after-1r-max-1` | 248 | `-$62.4036` | `0.7089` | `-$0.2516` | `-$74.6438` | `-$40.2639` | `-$61.1558` | `15.06%` | `61.29%` | `-$90.6548` | `-$121.3860` | reject |
| `orb-atr-trail-1-0-max-1` | 248 | `-$80.4459` | `0.4606` | `-$0.3244` | `-$80.7997` | `-$35.0770` | `-$48.4435` | `16.64%` | `36.80%` | `-$108.6962` | `-$139.4264` | reject |
| `orb-atr-trail-1-5-max-1` | 248 | `-$65.8232` | `0.6098` | `-$0.2654` | `-$65.9474` | `-$34.8241` | `-$46.6168` | `24.69%` | `52.03%` | `-$94.0730` | `-$124.8028` | reject |
| `orb-atr-trail-2-0-max-1` | 248 | `-$73.5990` | `0.6131` | `-$0.2968` | `-$75.4477` | `-$45.9991` | `-$58.8694` | `27.55%` | `58.58%` | `-$101.8472` | `-$132.5754` | reject |
| `orb-structure-trail-after-1r-max-1` | 248 | `-$66.0945` | `0.6840` | `-$0.2665` | `-$67.6276` | `-$35.7735` | `-$49.1337` | `14.22%` | `44.45%` | `-$94.3436` | `-$125.0727` | reject |

## Decision Rule

Keep an exit variant only if it improves costed expectancy or drawdown without
breaking concentration or collapsing under stress.

That did not happen here.
