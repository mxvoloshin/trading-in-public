# SPY VWAP Pullback Deep Research Review

Date saved: 2026-06-29

This note captures the external deep-research review of the first
`spy-vwap-pullback` backtest. It is a research planning artifact, not financial
advice and not a live-trading approval.

## Verdict

The current SPY VWAP Pullback strategy should be rejected in its present form.
It may deserve one disciplined refinement cycle, but only to test whether a
regime-filtered trend-day continuation edge exists inside the broader idea.

The key failure is not the low win rate by itself. The key failure is that the
pre-cost edge is too small:

- gross PnL: `$2.3470` per one share over `278` closed trades
- gross expectancy: about `$0.0084` per completed trade
- cost-adjusted PnL with 1 bp one-way slippage and `$0.005/share` commission:
  `-$38.26795096`
- cost-adjusted profit factor: `0.8039`

That means the modeled execution-cost hurdle is far larger than the raw edge.
The baseline is not "almost live-ready"; it is structurally underpowered.

## Main Research Conclusion

VWAP should be treated as an intraday state variable and execution benchmark,
not as a standalone source of alpha. The research direction should move from:

```text
price above VWAP -> pull back -> buy
```

to:

```text
session shows directional imbalance -> VWAP retest/reclaim confirms continuation -> buy
```

The most credible path is a narrower trend-day continuation system that trades
less often, demands stronger context, and survives realistic execution costs.
If that narrower edge does not appear, the strategy should be replaced rather
than tuned further.

## Top Improvements To Test First

1. Improve execution realism before optimizing the signal.
   Use at least 1-minute data, and later quote-aware or spread-aware data, to
   check whether 5-minute next-bar-open fills are too optimistic, too
   pessimistic, or mis-specified.

2. Add a trend-day versus chop-day gate.
   Use opening-range behavior, first-30-minute return, VWAP slope, distance from
   VWAP, and relative volume to avoid ordinary mean-reverting sessions.

3. Split scheduled macro event days from ordinary sessions.
   CPI, PPI, payrolls, FOMC statement days, and Fed press-conference days should
   be tagged separately. They may need a dedicated model or may need to be
   excluded.

4. Add gap and relative-volume filters.
   A long-only continuation model should distinguish positive gap-and-hold
   sessions, failed gap sessions, downside recovery sessions, and low-energy
   sessions.

5. Add cross-index and volatility-regime confirmation.
   SPY continuation is more credible when QQQ/IWM confirm the move and the VIX
   regime is compatible with the strategy assumptions.

## Candidate Variants

These variants are not recommendations to trade. They are structured tests to
find out whether the idea has a real regime-specific edge.

| Variant | Entry | Exit | Risk / Time Rules | Expected Tradeoff |
| --- | --- | --- | --- | --- |
| Trend-day VWAP reclaim | At 10:00, require close above VWAP, above the 30-minute opening-range high, and elevated relative volume. After 10:00, buy a VWAP retest/reclaim that closes back above VWAP and above the prior close. | Exit on two consecutive closes below VWAP, close below signal-bar low, or end-of-day flatten. | Max one trade. No entries before 10:00 or after 14:30. Stop below signal-bar low or VWAP minus tolerance. | Fewer trades, higher selectivity. Best direct refinement of the current idea. |
| Gap-and-go pullback | Only trade positive gaps that hold above VWAP and day open by 10:00. Buy the first post-10:00 pullback resumption. | Exit on close below VWAP or end-of-day flatten. | Max one trade. No entries after 13:30. Skip extremely wide opening ranges. | Targets clean continuation days and avoids failed-gap churn. |
| Bearish-gap recovery reclaim | Only trade modest downside gaps that recover above VWAP and the opening-range midpoint by 10:00. Buy the first VWAP retest after reclaim. | Exit below VWAP, below recovery low, or end-of-day flatten. | Entries only 10:00-13:00. Smaller risk. | Tests "flush then stabilize" sessions. |
| Breadth-confirmed continuation | Current pullback idea, but only if SPY, QQQ, and IWM confirm by trading above VWAP or showing positive session returns. | Exit on SPY VWAP failure or broad confirmation failure. | Max two trades, but second trade only after profitable first trade. | Lower trade count, better market-quality filter. |
| Non-event trend filter | Trend-day VWAP reclaim, but exclude major scheduled macro event days. | Same as trend-day variant. | Same as trend-day variant. | Tests whether event-day noise is contaminating the baseline. |
| Event-day breakout | Only on FOMC or major macro days. Enter after the event if price breaks above VWAP and pre-event highs on abnormal volume. | Exit on post-event VWAP failure or end-of-day flatten. | Trade only event window. Smaller risk. | Tests whether event days need their own dedicated model. |

## Backtester Metrics To Add

The current summary is useful but not enough for the next research cycle. Add:

- expectancy per trade and per day
- median trade PnL
- MAE and MFE by trade
- holding-time distribution
- PnL by time-of-day bucket
- PnL by regime bucket
- gross edge consumed by costs
- slippage in cents/share and bps by clock time
- adverse-selection return after entry and exit fills
- trade frequency per day and trade clustering
- daily return distribution
- drawdown depth and duration
- contribution concentration from top trades and top days
- walk-forward out-of-sample summaries
- parameter sensitivity summaries

## Robustness Tests

Before any paper/live validation, test:

- 6-month train / 3-month test rolling walk-forward splits
- strict out-of-sample periods with frozen parameters
- small parameter perturbations around each selected setting
- day-level bootstrap and trade-level Monte Carlo reshuffling
- regime splits by trend/chop, gap bucket, relative volume, VIX regime, macro
  event day, time of day, and weekday
- slippage stress tests at 0.25, 0.5, 1, 2, 3, and 5 bps one way
- commission scenarios with and without minimum commission
- sensitivity to next-bar-open versus faster execution proxies

## Kill Criteria

Reject the refined strategy if any of these hold:

- net expectancy is non-positive in out-of-sample windows
- profitability disappears under plausible 2 bp one-way slippage
- small parameter changes flip the strategy from profitable to unprofitable
- more than half of net PnL comes from one narrow regime or the top 10 days
- the selected variant has fragile or non-repeatable walk-forward performance
- paper-trade fills are materially worse than the research model
- drawdown duration or loss streaks exceed operational tolerance

## Next Engineering Direction

The next implementation work should not tune the strategy directly. It should
make the research platform capable of proving whether the strategy deserves
tuning:

1. Add richer trade analytics and regime breakdowns.
2. Add research tags for time-of-day, opening range, gap, RVOL, and event days.
3. Add cost and execution stress reports.
4. Implement one or two high-priority variants behind the existing strategy
   registry.
5. Compare variants with the same execution engine, same data cache, and same
   public-safe reporting format.

