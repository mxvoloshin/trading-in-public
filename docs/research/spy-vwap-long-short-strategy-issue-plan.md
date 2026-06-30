# SPY VWAP Long/Short Trend-Continuation Strategy Issue Plan

Repository: `mxvoloshin/trading-in-public`  
Instrument: SPY  
Timeframe: 5-minute bars  
Session: XNYS regular session only  
Primary strategy family: intraday VWAP trend continuation  
Secondary strategy family: VWAP range mean reversion  
Backtest baseline window: 2025-06-28 through 2026-06-27  
Position size: quantity 1 for normalized comparison  
Decision cost model: 1 bp one-way slippage + $0.005/share commission, no minimum commission  

---

# 1. Research Direction

The old long-only VWAP pullback strategy is no longer the correct baseline.

The new thesis is:

> VWAP is a directional intraday structure anchor.  
> The strategy should trade long on bullish VWAP trend-continuation setups and short on bearish VWAP trend-continuation setups.

The strategy should not blindly stack filters until the trade count collapses.

Instead, each filter must be tested independently against the clean long/short baseline.

---

# 2. Core Research Workflow

Use this workflow for every issue:

```text
1. Start from the clean long/short VWAP trend-continuation base.
2. Add feature calculations needed by the issue.
3. Export those features on every trade.
4. Run the base strategy unchanged.
5. Run base + this issue's filter only.
6. Compare results.
7. Record whether the filter is:
   - keep
   - reject
   - diagnostic-only
8. Do not stack the filter with previous filters unless the issue explicitly asks for a pairwise test.
```

The goal is to answer:

```text
Which filters actually improve the VWAP setup?
Which filters only reduce sample size?
Which filters help longs?
Which filters help shorts?
Which filters are useful only for reporting?
```

---

# 3. Minimum Trade Count Rules

For one year of SPY 5-minute data:

| Trades/year | Interpretation |
|---:|---|
| 250+ | Strong research sample |
| 150–250 | Acceptable |
| 80–150 | Thin but usable |
| 30–80 | Diagnostic only |
| < 30 | Not enough evidence |
| 7 | Ignore as statistical evidence |

Any variant with fewer than 80 trades/year should be treated as **diagnostic only**, unless later tested across many years and still has a large total sample.

---

# 4. Global Strategy Constants

Use configurable values. Do not hardcode parameters inside strategy logic.

Suggested config object:

```text
session_start_time = 09:30 America/New_York
session_end_time = 16:00 America/New_York
opening_range_minutes = 30
first_entry_time = 10:00 America/New_York
last_entry_time = 14:30 America/New_York
force_flat_time = 15:55 or session close handling
max_trades_per_day = 1 or 2
vwap_near_tolerance_atr = 0.25
atr_period_5m = 20
daily_sma_period = 20
daily_sma_slope_lookback = 5
rvol_lookback_sessions = 20
```

---

# 5. Required Metrics for Every Variant

Every issue must report:

```text
strategy_name
variant_name
trade_count
long_trade_count
short_trade_count
gross_total_pnl
costed_total_pnl
profit_factor
expectancy_per_trade
win_rate
average_win
average_loss
max_drawdown
first_half_pnl
second_half_pnl
worst_rolling_3_month_pnl
worst_rolling_6_month_pnl
largest_trade_pnl
largest_trade_as_pct_of_total_pnl
top_5_absolute_trades_as_pct_of_total_pnl
long_pnl
short_pnl
long_profit_factor
short_profit_factor
long_expectancy
short_expectancy
```

---

# 6. Required Trade Feature Export

Every trade should export these fields where available:

```text
trade_id
date
entry_time
exit_time
side
entry_price
exit_price
gross_pnl
costed_pnl
bars_held

session_open
session_high_so_far_at_entry
session_low_so_far_at_entry
session_vwap_at_entry
vwap_slope_at_entry

opening_range_high
opening_range_low
opening_range_mid
opening_range_range_pct
opening_range_return_pct
opening_range_close_location

prior_regular_session_close
opening_gap_pct

first_30m_volume
first_30m_rvol

atr_5m_20
distance_from_vwap_abs
distance_from_vwap_pct
distance_from_vwap_atr

distance_vwap_to_orh_atr
distance_vwap_to_orl_atr

signal_bar_open
signal_bar_high
signal_bar_low
signal_bar_close
signal_bar_range
signal_bar_body
signal_bar_close_location
signal_bar_body_pct_of_range

daily_sma_20
daily_sma_20_slope
daily_trend_state

entry_time_bucket
rvol_bucket
vwap_distance_bucket
opening_drive_bucket
regime_label_entry_time
regime_label_full_session_diagnostic
```

---

# 7. Implementation Issue Plan

---

## 000 - Create New Long/Short VWAP Trend-Continuation Base Strategy

Status: [ ]

### Goal

Create the new baseline strategy for the research program.

This baseline should represent the core directional VWAP trend-continuation thesis before additional filters are tested.

### Strategy Name

```text
spy-vwap-trend-continuation-long-short-base
```

### Base Session Rules

Implement:

```text
Use only XNYS regular session bars.
Ignore premarket and postmarket bars.
Calculate VWAP from regular-session bars only.
Do not enter during first 30 minutes.
Allow first entry at or after 10:00 New York time.
Do not open new trades after 14:30 New York time.
Force flat by end of day.
Use max_trades_per_day as configurable value.
Default max_trades_per_day = 1.
```

### Base VWAP Calculation

Session VWAP should reset every regular session.

Formula:

```text
typical_price = (high + low + close) / 3
bar_dollar_volume = typical_price * volume
session_vwap = cumulative(bar_dollar_volume) / cumulative(volume)
```

Use only completed bars.

No lookahead.

### Base Opening Range Calculation

Opening range should use the first 30 minutes of regular-session bars.

For 5-minute bars:

```text
opening_range_bars = 09:30, 09:35, 09:40, 09:45, 09:50, 09:55
opening_range_high = max(high of opening_range_bars)
opening_range_low = min(low of opening_range_bars)
opening_range_open = open of 09:30 bar
opening_range_close = close of 09:55 bar
opening_range_mid = (opening_range_high + opening_range_low) / 2
```

### Base Long Setup Rules

A long setup is allowed when all are true:

```text
current_time >= first_entry_time
current_time <= last_entry_time
current_close > session_vwap
session_vwap > prior_bar_session_vwap
current_close > opening_range_high
no open position
daily trade count < max_trades_per_day
```

Then require a VWAP pullback/reclaim condition:

```text
current_low <= session_vwap + vwap_near_tolerance_atr * atr_5m_20
current_close > session_vwap
current_close > prior_bar_close
```

Base long entry:

```text
enter long on next bar open
```

Base long exits:

```text
exit if close < session_vwap
exit if close < signal_bar_low
exit at force_flat_time / end of day
```

### Base Short Setup Rules

A short setup is allowed when all are true:

```text
current_time >= first_entry_time
current_time <= last_entry_time
current_close < session_vwap
session_vwap < prior_bar_session_vwap
current_close < opening_range_low
no open position
daily trade count < max_trades_per_day
```

Then require a VWAP pullback/rejection condition:

```text
current_high >= session_vwap - vwap_near_tolerance_atr * atr_5m_20
current_close < session_vwap
current_close < prior_bar_close
```

Base short entry:

```text
enter short on next bar open
```

Base short exits:

```text
exit if close > session_vwap
exit if close > signal_bar_high
exit at force_flat_time / end of day
```

### Fill Rules

Use realistic fill assumptions:

```text
Signal is generated on completed bar.
Trade can only enter on a later bar.
No same-bar entry after using same-bar close.
Apply transaction costs to every entry and exit.
```

### Definition of Done

- [ ] New strategy exists.
- [ ] Strategy supports long and short trades.
- [ ] VWAP resets each session.
- [ ] Opening range is calculated correctly.
- [ ] No lookahead bias exists.
- [ ] Cost model is applied.
- [ ] Reports show combined, long-only, and short-only results.
- [ ] Trade-level features are exported.
- [ ] This strategy becomes the baseline for all later issues.

## Result

Status: implemented in issue #62
Decision: keep as the new research baseline; reject as a paper/live candidate

Summary:
- Trades: 108
- Long trades: 53
- Short trades: 55
- Costed PnL: -$26.84532485
- Profit factor: 0.6377575564979527912617374164
- Expectancy: -$0.2485678226851851851851851852/trade
- Max DD: -$26.84532485
- Worst 6mo: -$17.27906212
- Long PnL: $0.40625628, PF 1.014498915990714929949733540, expectancy $0.007665212830188679245283018868
- Short PnL: -$27.25158113, PF 0.4087177298756999356941139564, expectancy -$0.4954832932727272727272727273
- Notes: One-year SPY 5-minute regular-session run used quantity 1, 1 bp one-way slippage, $0.005/share commission, and no minimum commission. The clean long/short base gives a usable but thin sample, but the edge is not viable after costs. Longs are roughly flat; shorts are the main damage center. This should be used as the comparison baseline for independent filter tests, not as a tradable candidate.

---

## 001 - Add Daily Trend Context Filter

Status: [ ]

### Goal

Test whether higher-timeframe daily trend context improves intraday VWAP continuation.

This filter should be side-aware:

```text
Bullish daily context helps long trades.
Bearish daily context helps short trades.
```

### Feature Calculation Rules

Use daily regular-session data.

Calculate:

```text
prior_regular_session_close
daily_sma_20
daily_sma_20_value_5_sessions_ago
daily_sma_20_slope = daily_sma_20 - daily_sma_20_value_5_sessions_ago
```

Define:

```text
bullish_daily_context =
    prior_regular_session_close > daily_sma_20
    and daily_sma_20_slope >= 0

bearish_daily_context =
    prior_regular_session_close < daily_sma_20
    and daily_sma_20_slope <= 0

neutral_daily_context =
    not bullish_daily_context
    and not bearish_daily_context
```

Important:

```text
Use only information known before the current session opens.
Do not use current session close in the daily SMA calculation.
```

### Filter Implementation Rules

Long trades allowed only when:

```text
bullish_daily_context == true
```

Short trades allowed only when:

```text
bearish_daily_context == true
```

Neutral context:

```text
No trades if the filter is enabled.
```

### Variants to Run

```text
000 base
000 base + daily trend context filter
```

### Required Bucket Reports

```text
PnL by daily_trend_state
PnL by daily_trend_state and side
Trade count by daily_trend_state and side
```

### Definition of Done

- [ ] Daily SMA is calculated without lookahead.
- [ ] Daily trend state is exported on every trade.
- [ ] Filter can be toggled on/off.
- [ ] Base vs filtered comparison is produced.
- [ ] Long and short results are reported separately.
- [ ] Decision is recorded: keep, reject, or diagnostic-only.

### Kill Conditions

Reject as a hard filter if:

```text
trade count drops below 80/year
costed expectancy does not improve
profit factor does not improve
worst rolling 6-month result does not improve
one side improves only because the other side barely trades
```

---

## 002 - Add Opening Drive Quality Filter

Status: [ ]

### Goal

Test whether the first 30 minutes identify directional session intent.

### Feature Calculation Rules

From the first 30 minutes of regular-session bars:

```text
first_30m_open = open of first regular-session bar
first_30m_high = max(high)
first_30m_low = min(low)
first_30m_close = close of last opening-range bar
first_30m_return_pct = (first_30m_close - first_30m_open) / first_30m_open
first_30m_range_pct = (first_30m_high - first_30m_low) / first_30m_open
```

Close location:

```text
first_30m_close_location =
    (first_30m_close - first_30m_low)
    / (first_30m_high - first_30m_low)
```

If range is zero:

```text
first_30m_close_location = 0.50
```

### Filter Implementation Rules

Long trades allowed only when:

```text
first_30m_return_pct >= 0
first_30m_close_location >= 0.60
```

Short trades allowed only when:

```text
first_30m_return_pct <= 0
first_30m_close_location <= 0.40
```

Optional stricter versions can be tested later, but not in the first implementation.

### Variants to Run

```text
000 base
000 base + opening drive quality filter
```

### Required Bucket Reports

Return bucket:

```text
<= -0.50%
-0.50% to -0.20%
-0.20% to 0%
0% to +0.20%
+0.20% to +0.50%
> +0.50%
```

Close location bucket:

```text
0.00 to 0.20
0.20 to 0.40
0.40 to 0.60
0.60 to 0.80
0.80 to 1.00
```

Report:

```text
PnL by first_30m_return bucket
PnL by first_30m_close_location bucket
PnL by side and opening drive bucket
```

### Definition of Done

- [ ] Opening-drive features are calculated.
- [ ] Features are exported on every trade.
- [ ] Filter can be toggled on/off.
- [ ] Base vs filtered comparison is produced.
- [ ] Bucket report is generated.
- [ ] Long and short results are separated.
- [ ] Decision is recorded.

### Kill Conditions

Reject as hard filter if:

```text
trade count drops below 80/year
only one narrow bucket works
filter improves PnL but worsens drawdown
filter is redundant with opening range breakout logic
```

---

## 003 - Replace RVOL Gate With RVOL Buckets

Status: [ ]

### Goal

Measure whether opening relative volume explains setup quality.

Do not start with a narrow hard threshold.

### Feature Calculation Rules

Calculate for each session:

```text
first_30m_volume = sum(volume of first 30m bars)
trailing_20_avg_first_30m_volume =
    average(first_30m_volume of previous 20 regular sessions)

first_30m_rvol =
    first_30m_volume / trailing_20_avg_first_30m_volume
```

Important:

```text
Use previous sessions only.
Do not include current session in the trailing average.
If fewer than 20 prior sessions exist, set first_30m_rvol = null.
```

Define buckets:

```text
missing_history
< 0.80
0.80 to 1.20
1.20 to 1.80
> 1.80
```

### Filter Implementation Rules

Implement three toggleable variants:

Loose RVOL filter:

```text
first_30m_rvol is null
or first_30m_rvol >= 0.80
```

Active RVOL filter:

```text
first_30m_rvol >= 1.20
```

Normal-to-active RVOL filter:

```text
first_30m_rvol >= 0.80
and first_30m_rvol <= 1.80
```

The `normal-to-active` version exists because very high RVOL can represent event-driven reversal risk.

### Variants to Run

```text
000 base
000 base + loose RVOL filter
000 base + active RVOL filter
000 base + normal-to-active RVOL filter
```

### Required Bucket Reports

```text
PnL by rvol_bucket
PnL by rvol_bucket and side
Trade count by rvol_bucket and side
```

### Definition of Done

- [ ] First 30-minute RVOL is calculated without lookahead.
- [ ] RVOL bucket is exported per trade.
- [ ] All three RVOL variants can be toggled.
- [ ] Base vs each RVOL variant is reported.
- [ ] Bucket report exists.
- [ ] Decision is recorded.

### Kill Conditions

Reject hard RVOL filtering if:

```text
active RVOL filter reduces trade count below 80/year
high RVOL is dominated by event days
RVOL improves PnL but increases concentration
RVOL is only useful as a diagnostic bucket
```

---

## 004 - Replace Fixed VWAP Distance With ATR or VWAP Band Distance

Status: [ ]

### Goal

Avoid chasing entries that are too extended from VWAP using volatility-normalized distance.

### Feature Calculation Rules

Calculate 5-minute ATR:

```text
true_range = max(
    high - low,
    abs(high - prior_close),
    abs(low - prior_close)
)

atr_5m_20 = average(true_range over previous 20 completed 5-minute bars)
```

Calculate VWAP distance:

```text
distance_from_vwap_abs = abs(close - session_vwap)
distance_from_vwap_pct = distance_from_vwap_abs / close
distance_from_vwap_atr = distance_from_vwap_abs / atr_5m_20
```

For longs:

```text
long_distance_from_vwap = close - session_vwap
```

For shorts:

```text
short_distance_from_vwap = session_vwap - close
```

Optional VWAP band calculation:

```text
vwap_std = standard deviation of typical_price around session_vwap using completed session bars
upper_vwap_band_1 = session_vwap + 1 * vwap_std
lower_vwap_band_1 = session_vwap - 1 * vwap_std
upper_vwap_band_2 = session_vwap + 2 * vwap_std
lower_vwap_band_2 = session_vwap - 2 * vwap_std
```

### Filter Implementation Rules

ATR-distance version:

Long trades allowed only when:

```text
close <= session_vwap + 1.00 * atr_5m_20
```

Short trades allowed only when:

```text
close >= session_vwap - 1.00 * atr_5m_20
```

VWAP-band version, if implemented:

Long trades allowed only when:

```text
close <= upper_vwap_band_1
```

Short trades allowed only when:

```text
close >= lower_vwap_band_1
```

### Variants to Run

```text
000 base
000 base + ATR VWAP distance filter
000 base + VWAP band distance filter, if implemented
```

### Required Bucket Reports

```text
0.00 to 0.25 ATR
0.25 to 0.50 ATR
0.50 to 1.00 ATR
1.00 to 1.50 ATR
> 1.50 ATR
```

Report:

```text
PnL by distance_from_vwap_atr bucket
PnL by side and distance_from_vwap_atr bucket
PnL by VWAP band bucket, if implemented
```

### Definition of Done

- [ ] ATR is calculated using completed bars only.
- [ ] VWAP distance features are exported per trade.
- [ ] ATR-distance filter can be toggled.
- [ ] Optional VWAP-band filter can be toggled if implemented.
- [ ] Base vs filtered comparison exists.
- [ ] Bucket report exists.
- [ ] Decision is recorded.

### Kill Conditions

Reject if:

```text
filter mostly removes winners
filter works only in one narrow threshold
trade count collapses below 80/year
ATR-normalized version is not better than fixed percent distance
```

---

## 005 - Add Signal-Bar Quality Rules

Status: [ ]

### Goal

Require better-quality VWAP reclaim/rejection signal bars.

### Feature Calculation Rules

For each signal bar:

```text
signal_bar_range = high - low
signal_bar_body = abs(close - open)
signal_bar_body_pct_of_range = signal_bar_body / signal_bar_range
signal_bar_close_location = (close - low) / signal_bar_range
```

If range is zero:

```text
signal_bar_body_pct_of_range = 0
signal_bar_close_location = 0.50
```

### Filter Implementation Rules

Long signal bar must satisfy:

```text
low <= session_vwap + vwap_near_tolerance_atr * atr_5m_20
close > session_vwap
close > prior_bar_close
signal_bar_close_location >= 0.50
```

Optional stronger long version:

```text
signal_bar_close_location >= 0.60
signal_bar_body_pct_of_range >= 0.30
```

Short signal bar must satisfy:

```text
high >= session_vwap - vwap_near_tolerance_atr * atr_5m_20
close < session_vwap
close < prior_bar_close
signal_bar_close_location <= 0.50
```

Optional stronger short version:

```text
signal_bar_close_location <= 0.40
signal_bar_body_pct_of_range >= 0.30
```

### Variants to Run

```text
000 base
000 base + basic signal-bar quality filter
000 base + stronger signal-bar quality filter
```

### Required Bucket Reports

```text
PnL by signal_bar_close_location bucket
PnL by signal_bar_body_pct_of_range bucket
PnL by side and signal_bar_close_location bucket
```

### Definition of Done

- [ ] Signal-bar features are calculated.
- [ ] Features are exported per trade.
- [ ] Basic signal-quality filter can be toggled.
- [ ] Strong signal-quality filter can be toggled.
- [ ] Base vs filtered comparisons exist.
- [ ] Long and short results are shown separately.
- [ ] Decision is recorded.

### Kill Conditions

Reject if:

```text
trade count collapses
win rate improves but expectancy worsens
large winners are removed
filter helps only one side and damages the other
```

---

## 006 - Change Entry to Break of Signal-Bar High/Low

Status: [ ]

### Goal

Enter only after price confirms continuation beyond the signal bar.

### Implementation Rules

This changes entry timing, not the setup conditions.

Long:

```text
A long signal bar forms.
Do not enter immediately.
On the next bar, enter only if price trades above signal_bar_high.
long_entry_price = max(next_bar_open, signal_bar_high)
If next bar high <= signal_bar_high, no trade.
```

Short:

```text
A short signal bar forms.
Do not enter immediately.
On the next bar, enter only if price trades below signal_bar_low.
short_entry_price = min(next_bar_open, signal_bar_low)
If next bar low >= signal_bar_low, no trade.
```

Important:

```text
Signal uses completed bar.
Entry happens only on following bar.
No same-bar entry.
No lookahead.
Costs apply to actual entry price.
```

### Optional Extension

Allow signal to remain valid for more than one bar:

```text
signal_valid_bars = 1 by default
optional test: signal_valid_bars = 2
```

Do not optimize this deeply.

### Variants to Run

```text
000 base
000 base + signal-bar break entry
000 base + signal-bar quality
000 base + signal-bar quality + signal-bar break entry
```

This pairwise test is allowed because signal quality and signal break are logically connected.

### Definition of Done

- [ ] Break-entry logic is implemented.
- [ ] Realistic fill price is used.
- [ ] Signal validity window is configurable.
- [ ] No lookahead exists.
- [ ] Base vs break-entry comparison exists.
- [ ] Pairwise signal-quality + break-entry comparison exists.
- [ ] Side-specific results are reported.
- [ ] Decision is recorded.

### Kill Conditions

Reject if:

```text
confirmation removes too many trades
costs erase benefit
win rate improves but expectancy worsens
large continuation winners are missed
```

---

## 007 - Add VWAP + Opening Range Confluence Filter

Status: [ ]

### Goal

Test whether VWAP continuation works better when VWAP is close to opening-range structure.

### Feature Calculation Rules

For every trade:

```text
distance_vwap_to_orh_abs = abs(session_vwap - opening_range_high)
distance_vwap_to_orl_abs = abs(session_vwap - opening_range_low)

distance_vwap_to_orh_atr = distance_vwap_to_orh_abs / atr_5m_20
distance_vwap_to_orl_atr = distance_vwap_to_orl_abs / atr_5m_20
```

### Filter Implementation Rules

Long trades allowed only when:

```text
distance_vwap_to_orh_atr <= 0.50
```

Short trades allowed only when:

```text
distance_vwap_to_orl_atr <= 0.50
```

Optional stricter variant:

```text
distance <= 0.25 ATR
```

Optional looser variant:

```text
distance <= 1.00 ATR
```

### Variants to Run

```text
000 base
000 base + VWAP/OR confluence <= 1.00 ATR
000 base + VWAP/OR confluence <= 0.50 ATR
000 base + VWAP/OR confluence <= 0.25 ATR
```

Do not pick the best threshold by PnL only. Check sample size and robustness.

### Required Bucket Reports

```text
0.00 to 0.25 ATR
0.25 to 0.50 ATR
0.50 to 1.00 ATR
> 1.00 ATR
```

Report:

```text
Long PnL by distance_vwap_to_orh_atr bucket
Short PnL by distance_vwap_to_orl_atr bucket
Trade count by side and confluence bucket
```

### Definition of Done

- [ ] VWAP-to-opening-range distance is calculated.
- [ ] Features are exported per trade.
- [ ] Multiple broad confluence thresholds are tested.
- [ ] Bucket report exists.
- [ ] Side-specific results exist.
- [ ] Decision is recorded.

### Kill Conditions

Reject if:

```text
trade count collapses
threshold selection looks parameter-mined
benefit comes from one or two trades
filter adds no value beyond existing OR breakout requirement
```

---

## 008 - Add R-Based Stop and Target

Status: [ ]

### Goal

Make exits risk-normalized using initial R.

### Feature Calculation Rules

At entry, determine signal-bar-based stop.

Long:

```text
initial_stop = min(signal_bar_low, session_vwap - 0.25 * atr_5m_20)
initial_risk = entry_price - initial_stop
```

Short:

```text
initial_stop = max(signal_bar_high, session_vwap + 0.25 * atr_5m_20)
initial_risk = initial_stop - entry_price
```

Reject trade if:

```text
initial_risk <= 0
initial_risk < minimum_realistic_risk
initial_risk > maximum_allowed_risk
```

Suggested risk bounds:

```text
minimum_realistic_risk = 0.05
maximum_allowed_risk = 2.00 * atr_5m_20
```

These should be configurable.

### Exit Implementation Rules

For each trade, support these exit modes:

Base exits:

```text
VWAP failure
structure failure
EOD flatten
```

R-target 1.0:

```text
target = entry_price + 1.0R for long
target = entry_price - 1.0R for short
```

R-target 1.5:

```text
target = entry_price + 1.5R for long
target = entry_price - 1.5R for short
```

R-target 2.0:

```text
target = entry_price + 2.0R for long
target = entry_price - 2.0R for short
```

Stop logic:

```text
Long exits if price trades at or below initial_stop.
Short exits if price trades at or above initial_stop.
```

If target and stop are both touched in same bar, use conservative ordering:

```text
For long: assume stop hit first unless open is beyond target.
For short: assume stop hit first unless open is beyond target.
```

### Variants to Run

```text
000 base exits
000 base + initial stop only
000 base + 1.0R target
000 base + 1.5R target
000 base + 2.0R target
000 base + trail after +1R, optional
```

### Definition of Done

- [ ] Initial stop is calculated.
- [ ] Initial risk is calculated.
- [ ] Invalid-risk trades are rejected.
- [ ] R-multiple is exported per trade.
- [ ] Multiple R-target variants are tested.
- [ ] Conservative same-bar stop/target handling is documented.
- [ ] Side-specific results exist.
- [ ] Decision is recorded.

### Kill Conditions

Reject if:

```text
R exits reduce expectancy
profitability depends on one exact R value
stops are unrealistically tight
same-bar assumptions dominate results
drawdown or concentration worsens
```

---

## 009 - Add Time Stop for Stalled Trades

Status: [ ]

### Goal

Exit trades that do not move in the expected direction quickly enough.

### Implementation Rules

Track bars since entry:

```text
bars_held = number of completed bars after entry
```

Track open R progress:

Long:

```text
open_r_progress = (current_close - entry_price) / initial_risk
```

Short:

```text
open_r_progress = (entry_price - current_close) / initial_risk
```

Time stop rule:

```text
If bars_held >= 4
and max_open_r_since_entry < 0.30
then exit at current bar close
```

Default:

```text
time_stop_bars = 4
required_progress_r = 0.30
```

Test broad variants only:

```text
3 bars / 0.30R
4 bars / 0.30R
6 bars / 0.30R
```

### Variants to Run

```text
000 base
000 base + time stop
000 base + R stop/target
000 base + R stop/target + time stop
```

The R stop/target + time stop pairwise test is allowed because time stop uses R progress.

### Definition of Done

- [ ] Bars held are tracked.
- [ ] Max open R progress is tracked.
- [ ] Time stop can be toggled.
- [ ] Broad variants are tested.
- [ ] Side-specific results are reported.
- [ ] Decision is recorded.

### Kill Conditions

Reject if:

```text
time stop exits winners too early
win rate improves but expectancy worsens
only one exact parameter works
rolling-window stability does not improve
```

---

## 010 - Add Regime Classification Reporting

Status: [ ]

### Goal

Add session-level regime reporting to understand when the strategy works or fails.

This should be reporting-first, not trading-first.

### Entry-Time Regime Feature Rules

Use only information known by the entry bar.

Calculate:

```text
first_30m_return_pct
first_30m_range_pct
first_30m_rvol
current_close_vs_vwap
current_close_vs_opening_range
vwap_slope
gap_pct
atr_regime
time_of_day
```

Suggested labels:

```text
bullish_trend_candidate
bearish_trend_candidate
range_candidate
event_like_high_volatility
unclear
```

Entry-time bullish trend candidate:

```text
first_30m_return_pct >= 0
close > session_vwap
close > opening_range_high
vwap_slope > 0
```

Entry-time bearish trend candidate:

```text
first_30m_return_pct <= 0
close < session_vwap
close < opening_range_low
vwap_slope < 0
```

Entry-time range candidate:

```text
abs(vwap_slope) is small
and price has crossed VWAP at least 2 times before entry
and close is inside opening range or near opening range midpoint
```

Event-like high-volatility candidate:

```text
first_30m_range_pct is in top historical bucket
or first_30m_rvol > 1.80
```

### Full-Session Diagnostic Labels

These may use future information and must not be used for entries.

Suggested labels:

```text
trend_up
trend_down
chop_or_mixed
high_volatility_reversal
```

Example diagnostic-only trend up:

```text
session_close > session_open
session_close near upper portion of session range
session spent majority of bars above VWAP
```

Example diagnostic-only trend down:

```text
session_close < session_open
session_close near lower portion of session range
session spent majority of bars below VWAP
```

### Required Reports

```text
PnL by entry-time regime
PnL by full-session diagnostic regime
PnL by side and regime
Trade count by regime
```

### Definition of Done

- [ ] Entry-time regime labels are calculated without lookahead.
- [ ] Full-session diagnostic labels are clearly marked as non-tradable.
- [ ] Regime labels are exported per trade.
- [ ] Reports exist by regime and side.
- [ ] No future-looking label is used in strategy decisions.
- [ ] Decision is recorded.

### Kill Conditions

Reject as trading filter if:

```text
it uses future information
it identifies regimes too late
it becomes too sparse
it does not improve independent filter tests
```

---

## 011 - Test Range-Day VWAP Mean-Reversion Playbook

Status: [ ]

### Goal

Test VWAP as a range-day mean-reversion anchor instead of a trend-continuation anchor.

This is a separate playbook.

### Strategy Name

```text
spy-vwap-range-reversion-base
```

### Required Features

Use:

```text
session_vwap
vwap_slope
vwap_bands or ATR distance from VWAP
VWAP cross count before entry
opening_range_pct
prior_day_high
prior_day_low
```

### Range-Day Candidate Rules

A range-day mean-reversion setup is allowed when:

```text
abs(vwap_slope) is small
price has crossed VWAP at least 2 times after 10:00
opening_range_pct is not extremely wide
price is inside prior regular-session high/low range
```

Suggested `abs(vwap_slope)` proxy:

```text
abs(session_vwap - vwap_3_bars_ago) <= 0.10 * atr_5m_20
```

### Long Mean-Reversion Rules

Long setup:

```text
price is below VWAP
close <= session_vwap - 1.0 * atr_5m_20
range-day candidate == true
```

Entry:

```text
enter long when close turns back upward
and close > prior_bar_close
```

Target:

```text
target = session_vwap
```

Stop:

```text
stop = recent swing low
or session_vwap - 1.5 * atr_5m_20
```

### Short Mean-Reversion Rules

Short setup:

```text
price is above VWAP
close >= session_vwap + 1.0 * atr_5m_20
range-day candidate == true
```

Entry:

```text
enter short when close turns back downward
and close < prior_bar_close
```

Target:

```text
target = session_vwap
```

Stop:

```text
stop = recent swing high
or session_vwap + 1.5 * atr_5m_20
```

### Variants to Run

```text
range-reversion base
range-reversion with 1.0 ATR band
range-reversion with 1.5 ATR band
```

Do not mix with trend-continuation strategy yet.

### Definition of Done

- [ ] Separate range-reversion strategy exists.
- [ ] It does not interfere with trend-continuation base.
- [ ] VWAP distance or VWAP bands are implemented.
- [ ] Long and short mean-reversion trades are reported separately.
- [ ] Results are compared against trend-continuation base.
- [ ] Decision is recorded.

### Kill Conditions

Reject if:

```text
negative after costs
gross edge is tiny
too many trades in chop with poor expectancy
requires many narrow filters to become positive
```

---

## 012 - Expand History and Run Validation Protocol

Status: [ ]

### Goal

Stop judging viability from one year.

### Implementation Rules

Extend SPY 5-minute history as far as practical.

Minimum:

```text
5 years
```

Preferred:

```text
10 years
```

If data availability is limited, document:

```text
available start date
available end date
missing sessions
split/dividend handling
timestamp timezone
regular-session filtering rules
```

### Validation Rules

Use:

```text
in-sample period
out-of-sample period
walk-forward or rolling yearly validation
```

Suggested:

```text
Research/train period = earliest 70%
Validation period = latest 30%
```

Also report by year:

```text
calendar_year
trade_count
costed_pnl
profit_factor
expectancy
max_drawdown
long_pnl
short_pnl
```

### Definition of Done

- [ ] Data history is expanded.
- [ ] Data quality is documented.
- [ ] Main strategy variants are rerun.
- [ ] Year-by-year table is generated.
- [ ] In-sample and out-of-sample results are separated.
- [ ] No strategy is accepted based only on the original one-year period.

### Kill Conditions

Reject if:

```text
strategy works only in the original year
strategy fails out-of-sample
strategy requires retuning every year
expanded-history PF is below 1.05 after costs
expanded-history expectancy is near zero or negative
```

---

## 013 - Add Cost Stress and Robustness Gates

Status: [ ]

### Goal

Make transaction costs and slippage central to the decision.

### Cost Scenarios

Run:

```text
base_cost:
1 bp one-way slippage + $0.005/share commission

stress_1:
2 bp one-way slippage + $0.005/share commission

stress_2:
3 bp one-way slippage + $0.005/share commission

stress_3:
1 bp one-way slippage + higher commission / minimum commission approximation
```

### Robustness Metrics

For every candidate, calculate:

```text
gross_total_pnl
costed_total_pnl
cost_impact
profit_factor_by_cost_scenario
expectancy_by_cost_scenario
max_drawdown_by_cost_scenario
worst_rolling_6_month_by_cost_scenario
largest_trade_pct_of_total_pnl
top_5_absolute_trades_pct_of_total_pnl
```

### Acceptance Gates

A strategy cannot move forward if:

```text
base-cost profit factor < 1.10
2 bp stress profit factor < 1.05
2 bp stress expectancy <= 0
top trade > 30% of total PnL
top 5 absolute trades > 100% of total PnL
```

### Definition of Done

- [ ] Multiple cost scenarios are implemented.
- [ ] Candidate variants can be rerun under each cost scenario.
- [ ] Cost stress report exists.
- [ ] Concentration metrics exist.
- [ ] Final decision uses costed results, not gross results.

### Kill Conditions

Reject if:

```text
cost stress erases the edge
profit factor collapses under 2 bp slippage
PnL depends on a few outliers
gross results are good but costed results are weak
```

---

## 014 - Final Research Decision

Status: [ ]

### Goal

Make a clear decision after the research cycle.

Do not keep adding filters indefinitely.

### Required Inputs

Final report must include:

```text
000 long/short base result
001 daily trend filter result
002 opening drive filter result
003 RVOL filter result
004 VWAP distance filter result
005 signal quality result
006 signal break result
007 VWAP/OR confluence result
008 R exit result
009 time stop result
010 regime report
011 range-reversion result, if implemented
012 expanded-history validation
013 cost stress report
```

### Required Comparison Table

| Variant | Trades | Long | Short | Costed PnL | PF | Exp/Trade | Max DD | Worst 6mo | Top Trade % | Top 5 Abs % | Verdict |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 000 Base L/S | | | | | | | | | | | |
| 001 Base + Daily Trend | | | | | | | | | | | |
| 002 Base + Opening Drive | | | | | | | | | | | |
| 003 Base + RVOL | | | | | | | | | | | |
| 004 Base + VWAP Distance | | | | | | | | | | | |
| 005 Base + Signal Quality | | | | | | | | | | | |
| 006 Base + Signal Break | | | | | | | | | | | |
| 007 Base + VWAP/OR Confluence | | | | | | | | | | | |
| 008 Base + R Exits | | | | | | | | | | | |
| 009 Base + Time Stop | | | | | | | | | | | |
| Best 2-filter Candidate | | | | | | | | | | | |
| Best 3-filter Candidate | | | | | | | | | | | |

### Acceptance Criteria

Candidate can move to paper trading only if:

```text
tested on at least 5 years of data
average trades/year >= 100
total trades >= 500 preferred
positive costed expectancy
base-cost profit factor >= 1.10
2 bp slippage stress profit factor >= 1.05
no single trade > 30% of total PnL
top 5 absolute trades <= 100% of total PnL
no catastrophic rolling 6-month window
long and short performance understood separately
no future-looking labels used for entry
no narrow parameter pocket required
works out-of-sample without retuning
```

### Pause Criteria

Pause and redesign if:

```text
some filters are diagnostically useful
but final candidate is too sparse
or final candidate is unstable
or one side works and the other side fails
or regime classification needs more work
```

### Kill Criteria

Reject the strategy family if:

```text
base long/short remains negative after costs
most filters only improve by reducing sample size
no single filter materially improves expectancy
combined filters collapse below useful trade count
expanded-history test fails
out-of-sample test fails
cost stress erases edge
PnL depends on outlier trades
```

### Final Decision Options

Choose exactly one:

```text
reject now
pause and redesign
continue one more research cycle
paper trade only after more validation
```

### Definition of Done

- [ ] Final report is created.
- [ ] Every issue result is included.
- [ ] Acceptance/pause/kill criteria are explicitly checked.
- [ ] Final decision is stated clearly.
- [ ] No more filters are added without a new research cycle.

---

# 8. Agent Instructions

When working through this file:

```text
Do not stack filters by default.
Do not select filters only by final PnL.
Do not ignore trade count.
Do not ignore long/short split.
Do not use future-looking labels for entry.
Do not accept one-year results as sufficient.
Do not accept gross-only profitability.
```

For each issue, the agent should append a result block:

```text
## Result

Status:
Decision: keep / reject / diagnostic-only

Summary:
- Trades:
- Long trades:
- Short trades:
- Costed PnL:
- Profit factor:
- Expectancy:
- Max DD:
- Worst 6mo:
- Notes:
```

---

# 9. Final Blunt Guidance

The goal is not to prove VWAP works.

The goal is to discover whether this statement is true:

> SPY intraday VWAP trend-continuation has a cost-adjusted edge when direction, session structure, and trade management are handled correctly.

If the answer is no, reject the strategy family and pivot.
