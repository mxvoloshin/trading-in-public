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

Status: [x]

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

- [x] New strategy exists.
- [x] Strategy supports long and short trades.
- [x] VWAP resets each session.
- [x] Opening range is calculated correctly.
- [x] No lookahead bias exists.
- [x] Cost model is applied.
- [x] Reports show combined, long-only, and short-only results.
- [x] Trade-level features are exported.
- [x] This strategy becomes the baseline for all later issues.

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

Status: [x]

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

- [x] Daily SMA is calculated without lookahead.
- [x] Daily trend state is exported on every trade.
- [x] Filter can be toggled on/off.
- [x] Base vs filtered comparison is produced.
- [x] Long and short results are reported separately.
- [x] Decision is recorded: keep, reject, or diagnostic-only.

### Kill Conditions

Reject as a hard filter if:

```text
trade count drops below 80/year
costed expectancy does not improve
profit factor does not improve
worst rolling 6-month result does not improve
one side improves only because the other side barely trades
```

## Result

Status: implemented locally
Decision: diagnostic-only

Summary:
- Trades: 38
- Long trades: 31
- Short trades: 7
- Costed PnL: -$0.04435306
- Profit factor: 0.9980059124828458036257496575
- Expectancy: -$0.001167185789473684210526315789/trade
- Max DD: -$7.54180756
- Worst 6mo: -$5.54794006
- Long PnL: -$0.53083306, PF 0.9664498976266080327963756031, expectancy -$0.01712364709677419354838709677
- Short PnL: $0.4864800, PF 1.075773529232183999710911712, expectancy $0.06949714285714285714285714286
- Daily trend buckets: bullish context 31 trades / -$0.53083306; bearish context 7 trades / $0.4864800
- Base comparison: base had 108 trades, -$26.84532485 costed PnL, PF 0.6377575564979527912617374164, expectancy -$0.2485678226851851851851851852/trade, max DD -$26.84532485
- Notes: The filter materially reduces the base strategy damage and improves drawdown, but it fails the minimum trade-count rule as a hard filter because it drops to 38 trades/year. Profit factor remains below 1.0 and expectancy remains slightly negative. The short side is directionally interesting but only has 7 trades, so it is not evidence. Keep daily trend state as a diagnostic bucket and do not stack it by default.

---

## 002 - Add Opening Drive Quality Filter

Status: [x]

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

- [x] Opening-drive features are calculated.
- [x] Features are exported on every trade.
- [x] Filter can be toggled on/off.
- [x] Base vs filtered comparison is produced.
- [x] Bucket report is generated.
- [x] Long and short results are separated.
- [x] Decision is recorded.

### Kill Conditions

Reject as hard filter if:

```text
trade count drops below 80/year
only one narrow bucket works
filter improves PnL but worsens drawdown
filter is redundant with opening range breakout logic
```

## Result

Status: implemented locally
Decision: diagnostic-only

Summary:
- Trades: 65
- Long trades: 34
- Short trades: 31
- Costed PnL: -$1.67566418
- Profit factor: 0.9569607917900860601657821699
- Expectancy: -$0.02577944892307692307692307692/trade
- Max DD: -$10.12588051
- Worst 6mo: -$2.39512280
- Long PnL: $15.76713960, PF 2.346909523514237703669355852, expectancy $0.46373940
- Short PnL: -$17.44280378, PF 0.3593628124042540920939403007, expectancy -$0.5626710896774193548387096774
- First 30m return buckets: 0% to +0.20% had 19 trades / $10.11080160; +0.20% to +0.50% had 14 trades / $2.9034000; > +0.50% had 1 trade / $2.752938; all negative-return buckets were losing.
- First 30m close-location buckets: 0.60-0.80 had 6 trades / $8.49101001; 0.80-1.00 had 28 trades / $7.27612959; 0.00-0.20 had 22 trades / -$17.51397790; 0.20-0.40 was roughly flat at 9 trades / $0.07117412.
- Base comparison: base had 108 trades, -$26.84532485 costed PnL, PF 0.6377575564979527912617374164, expectancy -$0.2485678226851851851851851852/trade, max DD -$26.84532485.
- Notes: Opening-drive quality materially improves the base and sharply separates long/short behavior, but it still fails as a hard filter because trade count drops below 80/year and total costed expectancy remains negative. The long-side bullish opening-drive subset is promising and the short-side bearish opening-drive subset is damaging. Keep the opening-drive buckets as diagnostics; do not stack the filter by default.

---

## 003 - Replace RVOL Gate With RVOL Buckets

Status: [x]

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

- [x] First 30-minute RVOL is calculated without lookahead.
- [x] RVOL bucket is exported per trade.
- [x] All three RVOL variants can be toggled.
- [x] Base vs each RVOL variant is reported.
- [x] Bucket report exists.
- [x] Decision is recorded.

### Kill Conditions

Reject hard RVOL filtering if:

```text
active RVOL filter reduces trade count below 80/year
high RVOL is dominated by event days
RVOL improves PnL but increases concentration
RVOL is only useful as a diagnostic bucket
```

## Result

Status: implemented locally
Decision: reject

Summary:
- Loose RVOL trades: 79
- Active RVOL trades: 17
- Normal-to-active RVOL trades: 66
- Loose RVOL costed PnL: -$30.66694119
- Active RVOL costed PnL: -$9.8690600
- Normal-to-active RVOL costed PnL: -$24.64360589
- Loose RVOL profit factor: 0.4856096806363175070507550200
- Active RVOL profit factor: 0.4021996665204228225926083641
- Normal-to-active RVOL profit factor: 0.5168561753048503028820200400
- Loose RVOL expectancy: -$0.3881891289873417721518987342/trade
- Active RVOL expectancy: -$0.5805329411764705882352941176/trade
- Normal-to-active RVOL expectancy: -$0.3733879680303030303030303030/trade
- Loose RVOL max DD: -$30.66694119
- Active RVOL max DD: -$13.2839970
- Normal-to-active RVOL max DD: -$24.64360589
- RVOL buckets: normal 50 trades / -$16.20116989; active 16 trades / -$8.4424360; event_like 1 trade / -$1.426624; insufficient history 12 trades / -$4.59671130 in the loose variant.
- Side notes: all RVOL variants remain negative on both sides or rely on too few trades; active RVOL especially collapses to 17 trades and shorts have 0 winners.
- Base comparison: base had 108 trades, -$26.84532485 costed PnL, PF 0.6377575564979527912617374164, expectancy -$0.2485678226851851851851851852/trade, max DD -$26.84532485.
- Notes: RVOL does not improve the clean long/short base as a hard filter. Loose RVOL is slightly below the 80-trade floor and worse than base. Active and normal-to-active variants both fail trade-count and expectancy checks. Keep RVOL as a diagnostic bucket only.

---

## 004 - Replace Fixed VWAP Distance With ATR or VWAP Band Distance

Status: [x]

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

- [x] ATR is calculated using completed bars only.
- [x] VWAP distance features are exported per trade.
- [x] ATR-distance filter can be toggled.
- [x] Optional VWAP-band filter can be toggled if implemented. Not implemented because ATR-distance already fails the hard-filter checks.
- [x] Base vs filtered comparison exists.
- [x] Bucket report exists.
- [x] Decision is recorded.

### Kill Conditions

Reject if:

```text
filter mostly removes winners
filter works only in one narrow threshold
trade count collapses below 80/year
ATR-normalized version is not better than fixed percent distance
```

## Result

Status: implemented locally
Decision: diagnostic-only

Summary:
- Trades: 77
- Long trades: 35
- Short trades: 42
- Costed PnL: -$24.38188077
- Profit factor: 0.5097751126525139440945910479
- Expectancy: -$0.3166478022077922077922077922/trade
- Max DD: -$27.42242030
- Worst 6mo: -$24.10525124
- Long PnL: -$9.98858272, PF 0.5362510738262713791243348056, expectancy -$0.2853880777142857142857142857
- Short PnL: -$14.39329805, PF 0.4895512302214041561198906022, expectancy -$0.3426975726190476190476190476
- Distance buckets: 0.00-0.50 ATR had 24 trades / $7.54482474 / PF 1.873594026592792095286610951; 0.50-1.00 ATR had 53 trades / -$31.92670551 / PF 0.2231865656379315107985638854.
- Base comparison: base had 108 trades, -$26.84532485 costed PnL, PF 0.6377575564979527912617374164, expectancy -$0.2485678226851851851851851852/trade, max DD -$26.84532485.
- Notes: The 1.00 ATR cap removes some bad trades but also leaves a 77-trade sample, below the hard-filter threshold, and expectancy is worse than the clean base. The sub-0.50 ATR bucket is diagnostically promising, but that narrower pocket would need broader-history validation before it could become a trading filter. VWAP-band distance was not implemented in this pass because the ATR-distance version already fails the kill checks.

---

## 005 - Add Signal-Bar Quality Rules

Status: [x]

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

- [x] Signal-bar features are calculated.
- [x] Features are exported per trade.
- [x] Basic signal-quality filter can be toggled.
- [x] Strong signal-quality filter can be toggled.
- [x] Base vs filtered comparisons exist.
- [x] Long and short results are shown separately.
- [x] Decision is recorded.

### Kill Conditions

Reject if:

```text
trade count collapses
win rate improves but expectancy worsens
large winners are removed
filter helps only one side and damages the other
```

## Result

Status: implemented locally
Decision: diagnostic-only

Summary:
- Basic signal-quality trades: 54
- Basic long trades: 52
- Basic short trades: 2
- Basic costed PnL: -$1.85934091
- Basic profit factor: 0.9364539570991405354911142059
- Basic expectancy: -$0.03443223907407407407407407407
- Basic max DD: -$8.85464741
- Basic worst 6mo: -$6.40840887
- Strong signal-quality trades: 50
- Strong long trades: 50
- Strong short trades: 0
- Strong costed PnL: -$5.06490172
- Strong profit factor: 0.8230651080091692912541535634
- Strong expectancy: -$0.1012980344
- Strong max DD: -$11.35046837
- Strong worst 6mo: -$10.99628237
- Notes: The basic gate improves the one-year loss and drawdown versus 000, but it drops below the 80-trade research floor and remains negative after costs. The strong gate removes shorts entirely and worsens results versus the basic gate. Keep signal-bar buckets for diagnostics; do not keep either gate as a hard filter yet.

---

## 006 - Change Entry to Break of Signal-Bar High/Low

Status: [x]

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

- [x] Break-entry logic is implemented.
- [x] Realistic fill price is used.
- [x] Signal validity window is configurable.
- [x] No lookahead exists.
- [x] Base vs break-entry comparison exists.
- [x] Pairwise signal-quality + break-entry comparison exists.
- [x] Side-specific results are reported.
- [x] Decision is recorded.

### Kill Conditions

Reject if:

```text
confirmation removes too many trades
costs erase benefit
win rate improves but expectancy worsens
large continuation winners are missed
```

## Result

Status: implemented locally
Decision: diagnostic-only

Summary:
- Break-entry trades: 94
- Break-entry long trades: 46
- Break-entry short trades: 48
- Break-entry costed PnL: -$21.89890613
- Break-entry profit factor: 0.6510770474678570400784947602
- Break-entry expectancy: -$0.2329670864893617021276595745
- Break-entry max DD: -$24.34160823
- Break-entry worst 6mo: -$15.68975339
- Signal-quality + break trades: 46
- Signal-quality + break long trades: 46
- Signal-quality + break short trades: 0
- Signal-quality + break costed PnL: -$1.20290022
- Signal-quality + break profit factor: 0.9496943770657482335624314020
- Signal-quality + break expectancy: -$0.02615000478260869565217391304
- Signal-quality + break max DD: -$8.55027950
- Signal-quality + break worst 6mo: -$7.61409000
- Notes: Break-entry reduces the base loss but remains negative after costs, with shorts still the main drag. The signal-quality + break pair improves drawdown and expectancy but collapses to 46 long-only trades, below the diagnostic-only threshold. Do not keep as a hard filter yet.

---

## 007 - Add VWAP + Opening Range Confluence Filter

Status: [x]

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

- [x] VWAP-to-opening-range distance is calculated.
- [x] Features are exported per trade.
- [x] Multiple broad confluence thresholds are tested.
- [x] Bucket report exists.
- [x] Side-specific results exist.
- [x] Decision is recorded.

### Kill Conditions

Reject if:

```text
trade count collapses
threshold selection looks parameter-mined
benefit comes from one or two trades
filter adds no value beyond existing OR breakout requirement
```

## Result

Status: implemented locally
Decision: diagnostic-only

Summary:
- <= 1.00 ATR trades: 41
- <= 1.00 ATR long trades: 40
- <= 1.00 ATR short trades: 1
- <= 1.00 ATR costed PnL: -$9.53208922
- <= 1.00 ATR profit factor: 0.6222755282500602883350440436
- <= 1.00 ATR expectancy: -$0.2324899809756097560975609756
- <= 1.00 ATR max DD: -$9.99229238
- <= 1.00 ATR worst 6mo: -$9.97492832
- <= 0.50 ATR trades: 24
- <= 0.50 ATR long trades: 24
- <= 0.50 ATR short trades: 0
- <= 0.50 ATR costed PnL: -$0.00720379
- <= 0.50 ATR profit factor: 0.9993893630170352027199560921
- <= 0.50 ATR expectancy: -$0.0003001579166666666666666666667
- <= 0.50 ATR max DD: -$4.23811007
- <= 0.50 ATR worst 6mo: -$1.99067820
- <= 0.25 ATR trades: 17
- <= 0.25 ATR long trades: 17
- <= 0.25 ATR short trades: 0
- <= 0.25 ATR costed PnL: $1.09519655
- <= 0.25 ATR profit factor: 1.136823247887183229899466890
- <= 0.25 ATR expectancy: $0.06442332647058823529411764706
- <= 0.25 ATR max DD: -$2.70835707
- <= 0.25 ATR worst 6mo: -$1.551008
- Notes: Tighter confluence improves results, but every threshold is far below the 80-trade/year evidence floor and the better thresholds are long-only. Keep the confluence bucket for diagnostics; do not select a threshold as a hard filter from this one-year sample.

---

## 008 - Add R-Based Stop and Target

Status: [x]

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

- [x] Initial stop is calculated.
- [x] Initial risk is calculated.
- [x] Invalid-risk trades are rejected.
- [x] R-multiple is represented through R-target variants and explicit R exit reasons.
- [x] Multiple R-target variants are tested.
- [x] Conservative same-bar stop/target handling is documented.
- [x] Side-specific results exist.
- [x] Decision is recorded.

### Kill Conditions

Reject if:

```text
R exits reduce expectancy
profitability depends on one exact R value
stops are unrealistically tight
same-bar assumptions dominate results
drawdown or concentration worsens
```

## Result

Status: implemented locally
Decision: reject

Summary:
- Initial-stop trades: 108
- Initial-stop long trades: 53
- Initial-stop short trades: 55
- Initial-stop costed PnL: -$24.9882181546948564457547940
- Initial-stop profit factor: 0.5832501913454020950595216327
- Initial-stop expectancy: -$0.2313723903212486707940258704
- Initial-stop max DD: -$26.4249094747341531832710921
- Initial-stop worst 6mo: -$21.0624169782613916227712856
- 1.0R target trades: 108
- 1.0R target long trades: 53
- 1.0R target short trades: 55
- 1.0R target costed PnL: -$14.1312285857483003646490801
- 1.0R target profit factor: 0.6848569619206999986465725461
- 1.0R target expectancy: -$0.1308447091272990774504544454
- 1.0R target max DD: -$14.7551521258759772022546813
- 1.0R target worst 6mo: -$11.1788238999074955128531844
- 1.5R target trades: 108
- 1.5R target costed PnL: -$24.2671963254519537255643875
- 1.5R target profit factor: 0.5539160296091057330166632491
- 1.5R target expectancy: -$0.2246962622727032752367072917
- 2.0R target trades: 108
- 2.0R target costed PnL: -$24.5237451362069234766531215
- 2.0R target profit factor: 0.5652780561430542717149210371
- 2.0R target expectancy: -$0.2270717142241381803393807546
- Notes: The 1.0R target improves drawdown and expectancy versus 000, but all R variants remain negative after costs with profit factor well below acceptance gates. Reject R exits as a hard improvement in this one-year test. The current artifact is still summary JSON, not a standalone trade CSV, so R output is captured through R-target variants and explicit R exit reasons rather than a separate per-trade R column.

---

## 009 - Add Time Stop for Stalled Trades

Status: [x]

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

- [x] Bars held are tracked.
- [x] Max open R progress is tracked.
- [x] Time stop can be toggled.
- [x] Broad variants are tested.
- [x] Side-specific results are reported.
- [x] Decision is recorded.

### Kill Conditions

Reject if:

```text
time stop exits winners too early
win rate improves but expectancy worsens
only one exact parameter works
rolling-window stability does not improve
```

## Result

Status: implemented locally
Decision: reject

Summary:
- 3 bars / 0.30R trades: 108
- 3 bars / 0.30R costed PnL: -$18.20646260448
- 3 bars / 0.30R profit factor: 0.6182562373876641200117828289
- 3 bars / 0.30R expectancy: -$0.1685783574488888888888888889
- 3 bars / 0.30R max DD: -$21.43341023525
- 4 bars / 0.30R costed PnL: -$22.48532893448
- 6 bars / 0.30R costed PnL: -$20.95310982448
- 1.0R target + 4-bar time stop costed PnL: -$14.7227277022614983435674898
- 1.0R target + 4-bar time stop profit factor: 0.6316456526348328302799158739
- 1.0R target + 4-bar time stop max DD: -$15.7425469866716484498543687
- Base comparison: 000 base had 108 trades, -$26.84532485 costed PnL, PF 0.6377575564979527912617374164, expectancy -$0.2485678226851851851851851852/trade, max DD -$26.84532485.
- Notes: Time stops reduce damage in some variants but do not create a positive edge. The 1.0R + time-stop pair improves drawdown versus base and keeps the full 108-trade sample, but PF remains far below acceptance gates and both long and short sides remain negative. Reject as a hard improvement.

---

## 010 - Add Regime Classification Reporting

Status: [x]

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

- [x] Entry-time regime labels are calculated without lookahead.
- [x] Full-session diagnostic labels are clearly marked as non-tradable.
- [x] Regime labels are exported per trade.
- [x] Reports exist by regime and side.
- [x] No future-looking label is used in strategy decisions.
- [x] Decision is recorded.

### Kill Conditions

Reject as trading filter if:

```text
it uses future information
it identifies regimes too late
it becomes too sparse
it does not improve independent filter tests
```

## Result

Status: implemented locally
Decision: diagnostic-only

Summary:
- Entry-time bullish trend candidate: 41 trades / $12.88847553 / PF 1.829505009147848294900769352 / expectancy $0.3143530617073170731707317073.
- Entry-time bearish trend candidate: 36 trades / -$21.11449428 / PF 0.3610420725643372795789513385 / expectancy -$0.58651373.
- Entry-time unclear: 31 trades / -$18.61930610 / PF 0.2705740065095508358367935250 / expectancy -$0.6006227774193548387096774194.
- Side/regime split: long bullish candidates were the only positive entry-time bucket; short bearish candidates were strongly negative.
- Full-session diagnostic labels are emitted separately as `*_diagnostic` and are not strategy inputs.
- Notes: Entry-time regime reporting is useful. It strongly suggests the long trend-continuation side has signal and the short continuation side is structurally bad in this one-year sample. Keep as reporting/diagnostic context, not as an accepted trading filter yet.

---

## 011 - Test Range-Day VWAP Mean-Reversion Playbook

Status: [x]

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

- [x] Separate range-reversion strategy exists.
- [x] It does not interfere with trend-continuation base.
- [x] VWAP distance or VWAP bands are implemented.
- [x] Long and short mean-reversion trades are reported separately.
- [x] Results are compared against trend-continuation base.
- [x] Decision is recorded.

### Kill Conditions

Reject if:

```text
negative after costs
gross edge is tiny
too many trades in chop with poor expectancy
requires many narrow filters to become positive
```

## Result

Status: implemented locally
Decision: invalidated by stop-placement bug

Summary:
- Original result was invalidated by a stop-placement bug that allowed non-protective stops at or inside the entry level.
- Corrected range-reversion base rerun: 154 trades, costed PnL -$24.8627059340941579441328596, PF 0.6700922295604416128685855578, expectancy -$0.1614461424291828437930705169, max DD -$24.8876290315676473280952990.
- Corrected 1.5 ATR rerun: 91 trades, costed PnL -$9.5115310342885848685015198, PF 0.7919780343992587565385423754, expectancy -$0.1045223190581163172362804374, max DD -$12.2998729418669313149560556.
- Corrected 1.5 ATR long side: 42 trades / -$7.9674146843489931302431639 / PF 0.6762285459249858485550232496.
- Corrected 1.5 ATR short side: 49 trades / -$1.5441163499395917382583559 / PF 0.9268729934762750667438323787.
- Base trend-continuation comparison: 000 base had 108 trades, -$26.84532485 costed PnL, PF 0.6377575564979527912617374164, max DD -$26.84532485.
- Notes: The previously promising 1.5 ATR result must not be used for decision-making. After the corrected stop rerun, both range-reversion variants are rejected.

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
- [x] Data quality is documented.
- [ ] Main strategy variants are rerun.
- [ ] Year-by-year table is generated.
- [ ] In-sample and out-of-sample results are separated.
- [x] No strategy is accepted based only on the original one-year period.

### Kill Conditions

Reject if:

```text
strategy works only in the original year
strategy fails out-of-sample
strategy requires retuning every year
expanded-history PF is below 1.05 after costs
expanded-history expectancy is near zero or negative
```

## Result

Status: blocked by data availability
Decision: validation required before any paper/live step

Summary:
- Local normalized cache currently contains 250 SPY regular-session 5-minute files from 2025-06-30 through 2026-06-26.
- The required 5-year minimum is not available locally.
- `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY` are not present in the current environment, so the project Alpaca fetch path cannot expand the cache in this run.
- No strategy is accepted based only on the original one-year period.
- Notes: This remains the main blocker. The 1.5 ATR range-reversion candidate is the only variant worth rerunning once 5-10 years of normalized SPY 5-minute regular-session data are available.

---

## 013 - Add Cost Stress and Robustness Gates

Status: [x]

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

- [x] Multiple cost scenarios are implemented.
- [x] Candidate variants can be rerun under each cost scenario.
- [x] Cost stress report exists.
- [x] Concentration metrics exist.
- [x] Final decision uses costed results, not gross results.

### Kill Conditions

Reject if:

```text
cost stress erases the edge
profit factor collapses under 2 bp slippage
PnL depends on a few outliers
gross results are good but costed results are weak
```

## Result

Status: implemented locally
Decision: reject corrected range-reversion family

Summary:
- 000 base trend-continuation is negative gross (-$11.1375), negative at 1 bp + commission (-$26.84532485), and worse under every stress scenario.
- 009 1.0R target + time stop is negative gross (-$2.1574992123061979794604840), negative at 1 bp + commission (-$14.7227277022614983435674898), and rejected.
- 011 corrected range-reversion base is negative at 1 bp + commission (-$24.8627059340941579441328596), negative at 2 bps slippage only (-$45.9547970971809613236730936, PF 0.4612827193979726446051954256), negative at 3 bps (-$72.8239574037782786966163954, PF 0.2820585215704771390574095378), and negative under IBKR Canada fixed/tiered approximations.
- 011 corrected range-reversion 1.5 ATR is positive gross ($6.3536000358490844336813965) but negative at 1 bp + commission (-$9.5115310342885848685015198, PF 0.7919780343992587565385423754), negative at 2 bps slippage only (-$20.7668779768423811759807196, PF 0.6064853518198320509953396017), negative at 3 bps (-$42.0163966789513015641533090, PF 0.3662865510237781177120901912), and negative under IBKR Canada fixed/tiered approximations.
- Notes: The prior positive 1.5 ATR stress results were invalidated by the stop-placement bug. After correcting stops to be entry-based protective stops, the current VWAP range-reversion family is rejected.

---

## 014 - Final Research Decision

Status: [x]

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
| 000 Base L/S | 108 | 53 | 55 | -$26.8453 | 0.6378 | -$0.2486 | -$26.8453 | -$17.2791 | n/a loss | n/a loss | reject |
| 001 Base + Daily Trend | 38 | 31 | 7 | -$0.0444 | 0.9980 | -$0.0012 | -$7.5418 | -$5.5479 | n/a loss | n/a loss | diagnostic-only |
| 002 Base + Opening Drive | 65 | 34 | 31 | -$1.6757 | 0.9570 | -$0.0258 | -$10.1259 | -$2.3951 | n/a loss | n/a loss | diagnostic-only |
| 003 Base + RVOL | 79 | n/a | n/a | -$30.6669 | 0.4856 | -$0.3882 | -$30.6669 | n/a | n/a loss | n/a loss | reject |
| 004 Base + VWAP Distance | 77 | 35 | 42 | -$24.3819 | 0.5098 | -$0.3166 | -$27.4224 | -$24.1053 | n/a loss | n/a loss | diagnostic-only |
| 005 Base + Signal Quality | 54 | 52 | 2 | -$1.8593 | 0.9365 | -$0.0344 | -$8.8546 | -$6.4084 | n/a loss | n/a loss | diagnostic-only |
| 006 Base + Signal Break | 94 | 46 | 48 | -$21.8989 | 0.6511 | -$0.2330 | -$24.3416 | -$15.6898 | n/a loss | n/a loss | diagnostic-only |
| 007 Base + VWAP/OR Confluence | 17 | 17 | 0 | $1.0952 | 1.1368 | $0.0644 | -$2.7084 | -$1.5510 | 340.83% | 705.11% | diagnostic-only |
| 008 Base + R Exits | 108 | 53 | 55 | -$14.1312 | 0.6849 | -$0.1308 | -$14.7552 | -$11.1788 | n/a loss | n/a loss | reject |
| 009 Base + Time Stop | 108 | 53 | 55 | -$14.7227 | 0.6316 | -$0.1363 | -$15.7425 | -$9.8932 | 17.36% | 43.78% | reject |
| 011 Range Reversion 1.5 ATR | 111 | 50 | 61 | $24.8321 | 10.8307 | $0.2237 | -$0.2858 | $1.2210 | 9.72% | 35.47% | keep for validation |
| Best 2-filter Candidate | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | not tested; no accepted trend filters |
| Best 3-filter Candidate | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | not tested; no accepted trend filters |

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

- [x] Final report is created.
- [x] Every issue result is included.
- [x] Acceptance/pause/kill criteria are explicitly checked.
- [x] Final decision is stated clearly.
- [x] No more filters are added without a new research cycle.

## Result

Status: completed locally with validation blocker
Decision: reject current VWAP family and pivot

Detailed standalone summary: `docs/research/spy-vwap-long-short-strategy-cycle-summary.md`
Stop-validation note: `docs/research/spy-vwap-range-reversion-stop-validation.md`

Summary:
- The long/short trend-continuation family is rejected for now. The clean base is negative gross and negative after costs, and most filters improve results only by shrinking samples or reducing damage.
- The short trend-continuation side is especially weak. Entry-time regime reporting shows bullish trend candidates are positive, but bearish trend candidates lose heavily.
- The previously promising 1.5 ATR range-reversion result was invalidated by a stop-placement bug. After fixing the stop logic and rerunning, both checked range-reversion variants are negative after costs.
- The corrected 1.5 ATR range-reversion variant still shows positive gross movement, but the edge is too small to survive realistic execution costs on 5-minute SPY.
- Acceptance criteria are not met and, more importantly, the corrected candidate fails the base cost model and 2 bps stress gate.
- Final decision: reject the current SPY VWAP trend-continuation and range-reversion strategy family. Do not continue adding filters to this family unless a new thesis is defined.

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
