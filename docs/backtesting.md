# Minimal Backtest Runner

The first backtest runner proves the path from normalized historical bars to
shared strategy decisions, broker-neutral order intents, simulated fills, and a
small local summary artifact.

This is engineering validation only. It is not financial advice, a performance
claim, or a complete research platform.

## Prepare Data

Fetch or otherwise populate the local normalized bar cache first:

```sh
uv run python -m trade_research_app market-data fetch \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular
```

The runner reads the project-owned normalized JSONL partitions through
`trade_data.LocalMarketDataStore`. It does not parse Alpaca raw responses or
provider-specific files directly.

## Run

```sh
uv run python -m trade_research_app backtest run \
  --strategy close-momentum \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular
```

By default, the summary is written under `.data/backtests/minimal/<strategy>/`,
which is gitignored. Use `--output path/to/summary.json` when you want a
specific local artifact path.

Execution cost assumptions are explicit CLI inputs:

```sh
uv run python -m trade_research_app backtest run \
  --strategy close-momentum \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular \
  --slippage-bps 1 \
  --commission-per-share 0.005 \
  --minimum-commission 1
```

The runner applies slippage one way: buy fills are adjusted above the next bar
open and sell fills are adjusted below the next bar open. Commissions are charged
on every simulated fill as `max(quantity * commission_per_share,
minimum_commission)`. Defaults are zero so gross and cost-adjusted runs are
deliberate and reproducible.

For IBKR Canada US-listed stocks/ETFs, the current research approximations are:

- `ibkr_ca_fixed_1bps`: `1` bp one-way slippage, `USD 0.005/share`, and a
  `USD 1.00` minimum commission per order. IBKR Canada describes fixed US
  stocks/ETFs pricing as all-inclusive, with exchange, clearing, and regulatory
  fees included in the fixed rate.
- `ibkr_ca_tiered_1bps`: `1` bp one-way slippage, `USD 0.0035/share`, and a
  `USD 0.35` minimum commission per order. Tiered pricing passes exchange,
  clearing, regulatory, and possible rebate effects through separately, so this
  is an approximation rather than a full venue-by-venue execution model.

Sources checked on 2026-06-30:

- IBKR Canada commissions page:
  <https://www.interactivebrokers.ca/en/pricing/commissions-home.php>
- IBKR US stocks/ETF detailed commission schedule:
  <https://www.interactivebrokers.com/en/pricing/commissions-stocks.php>
- IBKR Canada margin education:
  <https://www.interactivebrokers.ca/en/trading/margin-education.php>
- IBKR Canada margin rates:
  <https://www.interactivebrokers.ca/en/trading/margin-rates.php>

The older `slippage_1bps_commission` scenario is still useful as a no-minimum
per-share sensitivity check, but it should not be treated as the realistic
small-account decision model.

## Strategy Selection

Backtests select strategies by name with `--strategy`. The research app resolves
that name through the `trade_strategies` registry, then passes the selected
strategy into the runner. This keeps the runner responsible for execution, risk,
fills, positions, and PnL while strategies only emit shared
`trade_core.StrategyDecision` records.

To add another built-in strategy:

1. Add the strategy module under `packages/trade_strategies/src/trade_strategies/`.
2. Implement the shared `Strategy` interface.
3. Register its factory in `trade_strategies.registry`.
4. Add strategy-specific tests plus a CLI/runner test if the behavior affects
   backtest orchestration.

The initial built-in strategy is `close-momentum`:

- hold until at least two bars exist
- enter one long unit when the current close is above the previous close
- exit that long unit when the current close is below the previous close
- hold otherwise

Signals are close-based, so the runner treats each decision as available at the
bar close time and fills approved market intents at the next bar open. It does not
fill at the same close that created the signal.

The summary separates realized PnL from mark-to-market unrealized PnL. If the
data range ends with an open position or an approved order that has no next bar,
the output shows `ending_position`, `pending_orders`, `realized_pnl`,
`unrealized_pnl`, and `total_pnl` separately.

The JSON summary also includes research diagnostics for completed trades:

- expectancy per trade and per market-local exit day
- median, best, and worst completed trade PnL
- max drawdown duration measured in completed trades
- total slippage cost, total commission, and total execution cost
- average, median, and longest completed-trade holding time
- daily completed-trade breakdowns
- 30-minute market-local time-of-day breakdowns
- exit-reason breakdowns
- holding-time PnL buckets
- gap, opening-range, trend/chop, and relative-volume regime breakdowns
- max consecutive losing trades
- top trade/day contribution concentration
- first-half versus second-half chronological split summaries
- month-stepped rolling 3-month and 6-month summaries
- scheduled macro event-day versus ordinary-session breakdowns
- same-session post-exit max favorable move, measured from each simulated exit
  fill to the later session high for the same long-side position

The first regime tags are reporting-only diagnostics:

- `gap_breakdown` compares the session open to the prior regular-session close.
- `opening_range_breakdown` classifies the 10:00 New York close versus the
  first 30-minute opening range.
- `trend_breakdown` uses full-session VWAP direction and close location to
  split `trend_up`, `trend_down`, and `chop_or_mixed` sessions.
- `relative_volume_breakdown` compares session volume to the trailing 20-session
  average when enough prior sessions exist.

The macro event tags are also reporting-only diagnostics:

- `macro_event_day_breakdown` splits completed trades into `event_day` and
  `ordinary_session`.
- `macro_event_type_breakdown` groups trades by `cpi`, `ppi`,
  `employment_situation`, and `fomc_statement`. A trade can appear in more than
  one event-type bucket when two events fall on the same session.
- The first fixture lives in `trade_research_app.macro_events` and is manually
  maintained from public sources: BLS release calendars for CPI/PPI/Employment
  Situation and the Federal Reserve FOMC calendar.
- Source calendars:
  - BLS 2025 release calendar:
    <https://www.bls.gov/schedule/2025/home.htm>
  - BLS 2026 release calendar:
    <https://www.bls.gov/schedule/2026/home.htm>
  - Federal Reserve FOMC calendar:
    <https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm>

To update the macro fixture, edit the public-safe event list in
`apps/research/src/trade_research_app/macro_events.py`, add or update tests, and
rerun the backtest summary. Do not connect this to a private calendar or account.

## SPY VWAP Pullback Candidate

The live-candidate research strategy is available as `spy-vwap-pullback`:

```sh
uv run python -m trade_research_app backtest run \
  --strategy spy-vwap-pullback \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular
```

This strategy is a mechanical first pass at the SPY intraday research model:

- long-only until shorting mechanics are explicitly verified
- session VWAP calculated from 5-minute OHLCV bars
- first 5-minute regular-session bar used as the opening range
- no entries during the first 30 minutes
- entries require price above VWAP, VWAP rising, price above the opening range
  high, a pullback near VWAP, and trend resumption
- exits trigger on VWAP failure, pullback-structure failure, or end-of-day flat
  timing
- max two entries per day

VWAP is treated as an intraday price/volume benchmark that resets each trading
day. Schwab describes VWAP as the average intraday price adjusted for volume and
notes that traders use it as a reference for entry and exit decisions:
<https://www.schwab.com/learn/story/how-to-use-volume-weighted-indicators-trading>.

Opening-range logic is used only as context in this implementation. Separate ORB
research, including the Zarattini/Barbon/Aziz work on 5-minute opening range
breakouts, suggests ORB performance depends heavily on instrument selection,
relative volume, risk rules, and transaction costs rather than the opening range
alone:
<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284>.

### First One-Year SPY Result

Local cached data:

- symbol: `SPY`
- instrument: `SPY.US`
- timeframe: `5Min`
- market/session: `XNYS` regular session
- date range: `2025-06-28` through `2026-06-27`
- bars loaded: `19500`
- quantity: `1`

Backtest summary:

| Metric | Value |
| --- | ---: |
| Decisions | `19500` |
| Approved orders | `556` |
| Fills | `556` |
| Closed trades | `278` |
| Winning trades | `88` |
| Losing trades | `190` |
| Win rate | `31.65%` |
| Average win | `$1.9252` |
| Average loss | `-$0.8793` |
| Profit factor | `1.0140` |
| Expectancy / trade | `$0.0084424460` |
| Expectancy / day | `$0.0131853933` |
| Median trade PnL | `-$0.48` |
| Best trade PnL | `$10.41` |
| Worst trade PnL | `-$3.86` |
| Realized PnL | `$2.3470` |
| Unrealized PnL | `$0` |
| Total PnL | `$2.3470` |
| Max realized drawdown | `-$18.2102` |
| Max drawdown duration | `157` completed trades |
| Ending position | `0` |

Legacy no-minimum sensitivity scenario:

```sh
uv run python -m trade_research_app backtest run \
  --strategy spy-vwap-pullback \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular \
  --slippage-bps 1 \
  --commission-per-share 0.005 \
  --minimum-commission 0
```

| Metric | Value |
| --- | ---: |
| Slippage | `1` bp one way |
| Commission | `$0.005/share`, no minimum |
| Total commissions | `$2.780` |
| Closed trades | `278` |
| Winning trades | `83` |
| Losing trades | `195` |
| Win rate | `29.86%` |
| Average win | `$1.8906` |
| Average loss | `-$1.0010` |
| Profit factor | `0.8039` |
| Expectancy / trade | `-$0.1376544999` |
| Expectancy / day | `-$0.2149884885` |
| Median trade PnL | `-$0.6295165` |
| Best trade PnL | `$10.265437` |
| Worst trade PnL | `-$4.004212` |
| Realized PnL | `-$38.26795096` |
| Total PnL | `-$38.26795096` |
| Total slippage cost | `$37.83495096` |
| Total execution costs | `$40.61495096` |
| Cost / closed trade | `$0.1460969459` |
| Max realized drawdown | `-$40.94114950` |
| Max drawdown duration | `265` completed trades |
| Average holding time | `115.47` minutes |
| Median holding time | `65` minutes |
| Longest holding time | `345` minutes |
| Average post-exit max favorable move | `$1.6806` |
| Median post-exit max favorable move | `$1.0526` |
| Max post-exit max favorable move | `$12.912716` |

The first time-of-day breakdown shows a useful diagnostic, not a tradable rule:
most intraday exit buckets lose money after costs, while `15:30-16:00` is
positive because many winners are forced flat near the end of the day. That
suggests the next research slice should examine hold time, exit timing, and
whether early exits are cutting trend-day winners too soon.

The hold-time diagnostics make the exit problem sharper:

| Holding time | Closed trades | Win rate | Total PnL | Expectancy | Median post-exit favorable move |
| --- | ---: | ---: | ---: | ---: | ---: |
| `00-30m` | `91` | `2.20%` | `-$96.35379742` | `-$1.0588` | `$1.779225` |
| `30-60m` | `40` | `0.00%` | `-$41.38488091` | `-$1.0346` | `$1.381199` |
| `60-120m` | `42` | `4.76%` | `-$37.21159462` | `-$0.8860` | `$1.064876` |
| `120m+` | `105` | `75.24%` | `$136.68232199` | `$1.3017` | `$0.618012` |

The exit-reason breakdown points to `close_below_vwap` as the main damage
center: `185` closed trades, `7.03%` win rate, `-$165.21270694` total PnL, and
a median same-session post-exit favorable move of `$1.558434`. The smaller
`pullback_structure_failed` bucket is also entirely losing (`15` trades,
`-$14.78125299`) and still has a `$1.522944` median post-exit favorable move.
The data does not say "hold everything longer"; it says the current early-exit
rules are often paying the loss before the session's later upside develops.
Any next variant should therefore test trend-day continuation context before
loosening exits.

The first regime split supports that direction:

| Regime tag | Closed trades | Win rate | Total PnL | Expectancy |
| --- | ---: | ---: | ---: | ---: |
| `trend_up` | `144` | `49.31%` | `$77.38624234` | `$0.5374` |
| `chop_or_mixed` | `91` | `13.19%` | `-$65.88044519` | `-$0.7240` |
| `trend_down` | `43` | `0.00%` | `-$49.77374811` | `-$1.1575` |

This is still a descriptive split with full-session information, not a tradable
filter by itself. It says the next implementable candidate should approximate
`trend_up` conditions from information available early enough in the session,
then compare against the same execution-cost stress.

### Symmetric Long/Short VWAP Pullback Candidate

The first short-side research variant is available as
`spy-vwap-pullback-long-short`:

```sh
uv run python -m trade_research_app backtest run \
  --strategy spy-vwap-pullback-long-short \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular
```

This variant preserves the original long setup and adds the bearish mirror:

- short entries require price below VWAP, falling VWAP, price below the opening
  range low, a retest near VWAP from below, and bearish trend resumption
- short exits trigger on VWAP reclaim, short pullback-structure failure, or
  end-of-day flat timing
- the backtest runner still owns simulated fills, PnL, costs, and reporting

Gross one-year result:

| Metric | Value |
| --- | ---: |
| Closed trades | `439` |
| Winning trades | `133` |
| Losing trades | `306` |
| Win rate | `30.30%` |
| Profit factor | `1.1835` |
| Expectancy / trade | `$0.1163984055` |
| Realized PnL | `$51.0989` |
| Total PnL | `$51.0989` |
| Max realized drawdown | `-$25.9630` |

Mild cost scenario (`1` bp one-way slippage and `$0.005/share` commission):

| Metric | Value |
| --- | ---: |
| Closed trades | `439` |
| Winning trades | `128` |
| Losing trades | `311` |
| Win rate | `29.16%` |
| Profit factor | `0.9600` |
| Expectancy / trade | `-$0.0294275155` |
| Realized PnL | `-$12.91867929` |
| Total PnL | `-$12.91867929` |
| Total commissions | `$4.390` |
| Total slippage cost | `$59.62757929` |
| Total execution costs | `$64.01757929` |
| Max realized drawdown | `-$34.74503443` |

The short side does fix the obvious down-day problem. In the costed run,
`trend_down` sessions improve from the long-only baseline's `-$49.77374811` to
`$46.32176131`. The costed split is:

| Regime tag | Closed trades | Win rate | Total PnL | Expectancy |
| --- | ---: | ---: | ---: | ---: |
| `trend_up` | `160` | `37.50%` | `$18.97873663` | `$0.1186` |
| `trend_down` | `131` | `30.53%` | `$46.32176131` | `$0.3536` |
| `chop_or_mixed` | `148` | `18.92%` | `-$78.21917723` | `-$0.5285` |

The tradeoff is that the symmetric candidate adds many more trades, so chop and
execution costs become the main damage centers. It is a better research result
than the long-only baseline, but still not live-ready under the same cost
assumption.

Cost-stress reports can be generated with:

```sh
uv run python -m trade_research_app backtest cost-stress \
  --strategy spy-vwap-pullback \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular
```

The first SPY baseline stress grid shows how quickly costs consume the gross
edge:

| Scenario | Total PnL | Expectancy / trade | Profit factor | Cost drag from gross | Gross edge consumed |
| --- | ---: | ---: | ---: | ---: | ---: |
| `gross` | `$2.3470` | `$0.0084424460` | `1.0140` | `$0.0000` | `0.00x` |
| `commission_only` | `-$0.4330` | `-$0.0015575540` | `0.9974` | `$2.7800` | `1.18x` |
| `slippage_0_25bps` | `-$7.1117377400` | `-$0.0255817904` | `0.9590` | `$9.4587377400` | `4.03x` |
| `slippage_0_5bps` | `-$16.570475480` | `-$0.0596060269` | `0.9080` | `$18.917475480` | `8.06x` |
| `slippage_1bps` | `-$35.48795096` | `-$0.1276544999` | `0.8164` | `$37.83495096` | `16.12x` |
| `slippage_1bps_commission` | `-$38.26795096` | `-$0.1376544999` | `0.8039` | `$40.61495096` | `17.31x` |
| `ibkr_ca_fixed_1bps` | `-$591.48795096` | `-$2.1276544999` | `0.0759` | `$593.83495096` | `253.02x` |
| `ibkr_ca_tiered_1bps` | `-$230.08795096` | `-$0.8276544999` | `0.3198` | `$232.43495096` | `99.03x` |

The stress report also carries the median same-session post-exit favorable move
for each scenario. That keeps exit-quality context visible while comparing cost
drag, but it still does not turn this baseline into a live candidate.

The symmetric long/short stress grid shows a stronger but still fragile gross
edge:

| Scenario | Total PnL | Expectancy / trade | Profit factor | Cost drag from gross | Gross edge consumed |
| --- | ---: | ---: | ---: | ---: | ---: |
| `gross` | `$51.0989` | `$0.1163984055` | `1.1835` | `$0.0000` | `0.00x` |
| `commission_only` | `$46.7089` | `$0.1063984055` | `1.1660` | `$4.3900` | `0.09x` |
| `slippage_0_25bps` | `$36.1920051775` | `$0.0824419252` | `1.1253` | `$14.9068948225` | `0.29x` |
| `slippage_0_5bps` | `$21.285110355` | `$0.0484854450` | `1.0711` | `$29.813789645` | `0.58x` |
| `slippage_1bps` | `-$8.52867929` | `-$0.0194275155` | `0.9734` | `$59.62757929` | `1.17x` |
| `slippage_1bps_commission` | `-$12.91867929` | `-$0.0294275155` | `0.9600` | `$64.01757929` | `1.25x` |
| `ibkr_ca_fixed_1bps` | `-$886.52867929` | `-$2.0194275155` | `0.1334` | `$937.62757929` | `18.35x` |
| `ibkr_ca_tiered_1bps` | `-$315.82867929` | `-$0.7194275155` | `0.4264` | `$366.92757929` | `7.18x` |

### Trend-Day VWAP Reclaim Candidate

The first narrowed trend-continuation candidate is available as
`trend-day-vwap-reclaim`:

```sh
uv run python -m trade_research_app backtest run \
  --strategy trend-day-vwap-reclaim \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular
```

This variant is long-only and intentionally stricter than the baseline:

- no entries before 10:00 New York time
- no entries after 14:30 New York time
- max one trade per day
- requires price above the opening-range high and rising VWAP
- enters only after a VWAP retest/reclaim that closes above VWAP and above the
  prior close
- exits on two consecutive closes below VWAP, a close below the signal-bar low,
  or end-of-day flattening

One-year comparison, same cached SPY 5-minute regular-session data and quantity
`1`:

| Strategy | Cost model | Closed trades | Total PnL | Expectancy / trade | Profit factor | Max DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `spy-vwap-pullback` | 1 bp + `$0.005/share` | `278` | `-$38.26795096` | `-$0.1376544999` | `0.8039` | `-$40.94114950` |
| `spy-vwap-pullback-long-short` | 1 bp + `$0.005/share` | `439` | `-$12.91867929` | `-$0.0294275155` | `0.9600` | `-$34.74503443` |
| `trend-day-vwap-reclaim` | gross | `176` | `$23.1870` | `$0.1317443182` | `1.2173` | `-$14.2609` |
| `trend-day-vwap-reclaim` | 1 bp + `$0.005/share` | `176` | `-$2.57240342` | `-$0.0146159285` | `0.9793` | `-$16.33685627` |

Cost stress for `trend-day-vwap-reclaim`:

| Scenario | Total PnL | Expectancy / trade | Profit factor | Gross edge consumed |
| --- | ---: | ---: | ---: | ---: |
| `gross` | `$23.1870` | `$0.1317443182` | `1.2173` | `0.00x` |
| `slippage_0_5bps` | `$11.187298290` | `$0.0635641948` | `1.0974` | `0.52x` |
| `slippage_1bps` | `-$0.81240342` | `-$0.0046159285` | `0.9934` | `1.04x` |
| `slippage_1bps_commission` | `-$2.57240342` | `-$0.0146159285` | `0.9793` | `1.11x` |

The trend split explains both the promise and the rejection:

| Regime tag | Closed trades | Win rate | Total PnL | Expectancy |
| --- | ---: | ---: | ---: | ---: |
| `trend_up` | `90` | `55.56%` | `$78.45697583` | `$0.8717` |
| `chop_or_mixed` | `55` | `10.91%` | `-$44.53386300` | `-$0.8097` |
| `trend_down` | `31` | `3.23%` | `-$36.49551625` | `-$1.1773` |

Robustness split:

- first half: `88` trades, `$0.37590525`, `$0.0043` expectancy
- second half: `88` trades, `-$2.94830867`, `-$0.0335` expectancy
- best rolling 6-month window: `$18.45239104`
- worst rolling 6-month window: `-$14.50730677`
- event days: `25` trades, `-$11.26096805`
- ordinary sessions: `151` trades, `$8.68856463`

Verdict: reject as a live/paper candidate under the current kill criteria. It is
better than the baseline and the symmetric long/short variant on gross edge,
trade count, and drawdown, but the legacy no-minimum cost model still flips it negative. The
useful research signal is that trend-up sessions are strongly positive while
chop/mixed and trend-down sessions are the damage centers; the next task should
focus on earlier tradable filters for those regimes rather than relaxing exits
or tuning a large parameter grid.

The robustness diagnostics keep both variants below the bar for live or
paper/live validation.

### Entry-Filtered Trend-Day VWAP Reclaim Candidate

Issue #36 adds a tradable trend/chop gate as
`trend-day-vwap-reclaim-entry-filter`:

```sh
uv run python -m trade_research_app backtest run \
  --strategy trend-day-vwap-reclaim-entry-filter \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular \
  --slippage-bps 1 \
  --commission-per-share 0.005 \
  --minimum-commission 0
```

The filter is applied inside the strategy before entry. It deliberately avoids
the full-session `trend_up` diagnostic because that label needs the final
session close and full-session VWAP. Instead, it uses only information known at
or before the simulated decision time:

- first 30-minute return from the session open must be non-negative
- current close must be above VWAP and above the opening-range high
- VWAP must be rising versus the previous completed bar
- entry close must not be more than `0.6%` above VWAP
- after 20 prior sessions exist, 9:30-10:00 volume must be at least `85%` of the
  trailing 20-session opening-window average

One-year comparison, same cached SPY 5-minute regular-session data and quantity
`1`:

| Strategy | Cost model | Closed trades | Total PnL | Expectancy / trade | Profit factor | Max DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `spy-vwap-pullback` | 1 bp + `$0.005/share` | `278` | `-$38.26795096` | `-$0.1376544999` | `0.8039` | `-$40.94114950` |
| `trend-day-vwap-reclaim` | 1 bp + `$0.005/share` | `176` | `-$2.57240342` | `-$0.0146159285` | `0.9793` | `-$16.33685627` |
| `trend-day-vwap-reclaim-entry-filter` | gross | `80` | `$14.8880` | `$0.1861` | `1.3190` | `-$13.1370` |
| `trend-day-vwap-reclaim-entry-filter` | 1 bp + `$0.005/share` | `80` | `$3.17277618` | `$0.0396597023` | `1.0580` | `-$16.97566632` |

Cost stress for `trend-day-vwap-reclaim-entry-filter`:

| Scenario | Total PnL | Expectancy / trade | Profit factor | Gross edge consumed |
| --- | ---: | ---: | ---: | ---: |
| `gross` | `$14.8880` | `$0.1861` | `1.3190` | `0.00x` |
| `commission_only` | `$14.0880` | `$0.1761` | `1.2983` | `0.05x` |
| `slippage_0_5bps` | `$9.43038809` | `$0.1178798511` | `1.1870` | `0.37x` |
| `slippage_1bps` | `$3.97277618` | `$0.0496597023` | `1.0733` | `0.73x` |
| `slippage_1bps_commission` | `$3.17277618` | `$0.0396597023` | `1.0580` | `0.79x` |
| `slippage_2bps` | `-$6.94244764` | `-$0.0867805955` | `0.8878` | `1.47x` |

The filter improves the current research candidate under the legacy no-minimum cost model:
it changes the narrowed trend-day reclaim from `-$2.57240342` to
`$3.17277618`, cuts closed trades from `176` to `80`, and improves expectancy
from `-$0.0146` to `$0.0397` per completed trade. It also materially reduces
exposure to the known damage buckets:

| Full-session diagnostic tag | Closed trades | Total PnL | Expectancy |
| --- | ---: | ---: | ---: |
| `trend_up` | `43` | `$36.79730918` | `$0.8558` |
| `chop_or_mixed` | `24` | `-$17.04855300` | `-$0.7104` |
| `trend_down` | `13` | `-$16.575980` | `-$1.2751` |

The robustness result is still not strong enough for live or paper/live
validation:

- first half: `40` trades, `$4.23663150`, `$0.1059` expectancy
- second half: `40` trades, `-$1.06385532`, `-$0.0266` expectancy
- best rolling 6-month window: `$18.26958699`
- worst rolling 6-month window: `-$15.04272632`
- event days: `11` trades, `-$3.434154`
- ordinary sessions: `69` trades, `$6.60693018`

Verdict: the issue #36 filter improves the strategy versus the prior candidates
under the legacy no-minimum cost model, but it does not clear the robustness bar
or the IBKR Canada small-account fee bar. The research result is "promising
filter, not live-ready strategy." The next research step should investigate why
recent rolling windows and event days remain negative before adding more entries
or loosening exits.

### Gap/RVOL VWAP Pullback Candidate

Issue #37 adds `gap-and-go-vwap-pullback`, a narrower positive-gap continuation
variant:

```sh
uv run python -m trade_research_app backtest run \
  --strategy gap-and-go-vwap-pullback \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular \
  --slippage-bps 1 \
  --commission-per-share 0.005 \
  --minimum-commission 0
```

The strategy starts from `trend-day-vwap-reclaim-entry-filter`, then adds a
gap/RVOL gate before entry:

- prior regular-session close must be known from the normalized bar stream
- session open must gap up between `0.2%` and `0.6%` versus that prior close
- the first 30-minute close must hold above the session open
- the entry close must still be above the session open
- the first 30-minute opening range must not exceed `1.0%` of the session open
- the existing entry-time trend/RVOL gate still applies: close above VWAP and
  opening-range high, rising VWAP, no more than `0.6%` extension above VWAP, and
  opening-window volume at least `85%` of trailing average once enough history
  exists

The first broad positive-gap attempt was rejected before finalizing the default:
`0.1%` to `1.2%` positive gaps produced `-$1.2750` gross and `-$6.99566150`
under the legacy no-minimum cost model. The narrower `0.2%` to `0.6%` gap pocket was the
only tested positive-gap slice that improved the current best candidate without
making the first/second chronological split worse.

One-year comparison, same cached SPY 5-minute regular-session data and quantity
`1`:

| Strategy | Cost model | Closed trades | Total PnL | Expectancy / trade | Profit factor | Max DD |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| `spy-vwap-pullback` | 1 bp + `$0.005/share` | `278` | `-$38.26795096` | `-$0.1376544999` | `0.8039` | `-$40.94114950` |
| `spy-vwap-pullback-long-short` | 1 bp + `$0.005/share` | `439` | `-$12.91867929` | `-$0.0294275155` | `0.9600` | `-$34.74503443` |
| `trend-day-vwap-reclaim` | 1 bp + `$0.005/share` | `176` | `-$2.57240342` | `-$0.0146159285` | `0.9793` | `-$16.33685627` |
| `trend-day-vwap-reclaim-entry-filter` | 1 bp + `$0.005/share` | `80` | `$3.17277618` | `$0.0396597023` | `1.0580` | `-$16.97566632` |
| `gap-and-go-vwap-pullback` | gross | `21` | `$7.1550` | `$0.3407142857` | `1.6981` | `-$5.1000` |
| `gap-and-go-vwap-pullback` | 1 bp + `$0.005/share` | `21` | `$4.07345250` | `$0.1939739286` | `1.3347` | `-$5.57270800` |
| `gap-and-go-vwap-pullback` | IBKR CA fixed approx | `21` | `-$37.71654750` | `-$1.7960260714` | `0.1488` | `-$37.71654750` |
| `gap-and-go-vwap-pullback` | IBKR CA tiered approx | `21` | `-$10.41654750` | `-$0.4960260714` | `0.5369` | `-$10.41654750` |

Cost stress for `gap-and-go-vwap-pullback`:

| Scenario | Total PnL | Expectancy / trade | Profit factor | Gross edge consumed |
| --- | ---: | ---: | ---: | ---: |
| `gross` | `$7.1550` | `$0.3407142857` | `1.6981` | `0.00x` |
| `commission_only` | `$6.9450` | `$0.3307142857` | `1.6691` | `0.03x` |
| `slippage_0_5bps` | `$5.71922625` | `$0.2723441071` | `1.5132` | `0.20x` |
| `slippage_1bps` | `$4.28345250` | `$0.2039739286` | `1.3558` | `0.40x` |
| `slippage_1bps_commission` | `$4.07345250` | `$0.1939739286` | `1.3347` | `0.43x` |
| `slippage_2bps` | `$1.41190500` | `$0.0672335714` | `1.1008` | `0.80x` |
| `slippage_3bps` | `-$1.45964250` | `-$0.0695067857` | `0.9091` | `1.20x` |
| `ibkr_ca_fixed_1bps` | `-$37.71654750` | `-$1.7960260714` | `0.1488` | `6.27x` |
| `ibkr_ca_tiered_1bps` | `-$10.41654750` | `-$0.4960260714` | `0.5369` | `2.46x` |

Regime and robustness split for the legacy no-minimum cost model:

| Bucket | Closed trades | Total PnL | Expectancy |
| --- | ---: | ---: | ---: |
| `trend_up` | `11` | `$10.7283460` | `$0.9753` |
| `chop_or_mixed` | `8` | `-$4.44807450` | `-$0.5560` |
| `trend_down` | `2` | `-$2.206819` | `-$1.1034` |
| `normal_relative_volume` | `13` | `$9.59721700` | `$0.7382` |
| `high_relative_volume` | `4` | `-$3.5176335` | `-$0.8794` |
| `low_relative_volume` | `4` | `-$2.006131` | `-$0.5015` |
| `ordinary_session` | `17` | `$5.75301150` | `$0.3384` |
| `event_day` | `4` | `-$1.679559` | `-$0.4199` |

Chronological and rolling-window split:

- first half: `11` trades, `$2.43432700`, `$0.2213` expectancy
- second half: `10` trades, `$1.6391255`, `$0.1639` expectancy
- best rolling 6-month window: `$9.62404049`
- worst rolling 6-month window: `-$4.813282`
- largest trade: `$5.252330`, which is `128.94%` of total PnL
- top 5 absolute trades: `$17.9206025`, representing `63.07%` of absolute trade
  PnL and `274.68%` of total PnL

Verdict: the gap/RVOL candidate improves the strategy on headline costed
metrics and has a better first/second split than the previous entry-time filter.
That headline was using the older no-minimum commission scenario. Under
IBKR Canada small-account minimum commissions, the one-share normalized result
turns negative on both fixed and tiered pricing. It is still not live-ready. The
result is based on only `21` trades, the largest trade is bigger than the final
profit, event days remain negative, and late rolling windows still fail. Treat
this as a promising research clue: modest positive gaps with normal opening
participation are worth further study, while broad positive-gap chasing and
high-RVOL gap sessions are not validated.

### Small Account Sizing Example

The backtest runner uses a fixed `--quantity`; it does not yet size orders from
account equity, risk per trade, buying power, or margin cushion. To estimate a
small account, choose a share quantity first, then rerun the same strategy with
that quantity and realistic costs.

For a `USD 5,000` account trading SPY over this sample:

- observed cached SPY close range: about `$615.70` to `$760.21`
- cash-sized conservative example: `6` shares keeps notional under `$5,000` near
  the sample high
- RegT-style margin example: IBKR Canada explains that rules-based margin can
  allow borrowing `50%` of the stock purchase value, so `13` shares is a rough
  `2x` buying-power example near the sample high
- margin buying power is not a profit target; it increases loss size, margin-call
  risk, and possible financing exposure
- these runs do not include tax effects, FX conversion, tiered venue-specific
  pass-through details, or margin interest

`gap-and-go-vwap-pullback`, same one-year sample:

| Quantity | Approx account interpretation | Cost model | Closed trades | Total PnL | Return on `$5,000` | Max DD | Profit factor |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: |
| `1` | normalized comparison only | IBKR CA fixed approx | `21` | `-$37.71654750` | `-0.75%` | `-$37.71654750` | `0.1488` |
| `1` | normalized comparison only | IBKR CA tiered approx | `21` | `-$10.41654750` | `-0.21%` | `-$10.41654750` | `0.5369` |
| `6` | cash-sized | IBKR CA fixed approx | `21` | `-$16.29928500` | `-0.33%` | `-$40.15207700` | `0.8397` |
| `6` | cash-sized | IBKR CA tiered approx | `21` | `$11.00071500` | `0.22%` | `-$35.35624800` | `1.1338` |
| `13` | rough `2x` margin-sized | IBKR CA fixed approx | `21` | `$13.68488250` | `0.27%` | `-$78.05520400` | `1.0738` |
| `13` | rough `2x` margin-sized | IBKR CA tiered approx | `21` | `$40.98488250` | `0.82%` | `-$74.15520400` | `1.2469` |

This answers the "how much would I earn with `$5,000`?" question only as a
historical what-if. The best current example is about `$40.98` over one year on
a rough `13`-share margin-sized run under the tiered approximation, before taxes,
FX, full pass-through fees, financing details, missed fills, and live execution
differences. That is not enough evidence to treat the strategy as working.

The entry-filtered predecessor also does not validate the path at `13` shares:
with IBKR CA tiered pricing it loses `-$4.35390966`, and with fixed pricing it
loses `-$108.35390966`. The apparent profitability is concentrated in the final
21-trade gap/RVOL subset, which raises overfitting risk.

For the costed long-only baseline:

- first half: `139` trades, `-$18.74215101`, `-$0.1348` expectancy
- second half: `139` trades, `-$19.52579995`, `-$0.1405` expectancy
- max consecutive losing trades: `9`
- largest single trade: `$10.265437`, which is `26.83%` of the final loss in
  the opposite direction and `2.92%` of absolute trade PnL
- top 10 absolute trades: `$42.18432706`, enough to offset `110.23%` of the
  final loss, but only `14.25%` of absolute trade PnL
- rolling 3-month windows are mostly negative; the best tested window,
  `2026-03-01_2026-05-30`, is only `$3.91798766`, while the worst
  `2025-12-01_2026-03-01` window is `-$20.14366155`

For the costed symmetric long/short candidate:

- first half: `220` trades, `$3.74328347`, `$0.0170` expectancy
- second half: `219` trades, `-$16.66196276`, `-$0.0761` expectancy
- max consecutive losing trades: `15`
- largest single trade: `$19.527631`, which offsets `151.16%` of the final
  loss but is only `3.08%` of absolute trade PnL
- top 10 absolute trades: `$96.62824263`, all net positive, offsetting `747.97%`
  of the final loss while representing only `15.25%` of absolute trade PnL
- rolling 6-month windows swing from `$8.76344093` to `-$26.63917923`, so the
  result is not chronologically stable

Kill-criteria interpretation: any next candidate must show positive net
expectancy after the IBKR Canada fixed and tiered approximations, avoid relying
on a handful of large trend captures to rescue many small losses, and remain
positive across at least the first/second chronological split plus the main
3-month and 6-month windows. If those diagnostics fail, the research result
should be rejected instead of tuned.

The macro event split adds another caution:

| Strategy | Bucket | Trades | Total PnL | Expectancy |
| --- | ---: | ---: | ---: | ---: |
| `spy-vwap-pullback` | Event days | `39` | `-$15.54924885` | `-$0.3987` |
| `spy-vwap-pullback` | Ordinary sessions | `239` | `-$22.71870211` | `-$0.0951` |
| `spy-vwap-pullback-long-short` | Event days | `69` | `$8.18227237` | `$0.1186` |
| `spy-vwap-pullback-long-short` | Ordinary sessions | `370` | `-$21.10095166` | `-$0.0570` |

The long-only baseline gets materially worse on event days, especially FOMC
statement sessions (`8` trades, `-$8.56993459`). The symmetric long/short
candidate is positive on tagged event days, helped most by Employment Situation
sessions (`18` trades, `$19.2062295`), but it still loses on ordinary sessions.
That is not enough to promote event-day trading; it means future candidates
should report event-day and ordinary-session results separately before any
paper/live validation.

Verdict: this first mechanical VWAP-pullback version is not live-ready. The
gross edge is effectively flat before commissions, spread, slippage, missed
fills, taxes, borrow/margin constraints, and operational risk. A one-share gross
profit of `$2.3470` over `278` completed trades is about `$0.0084` per completed
trade. Even the legacy no-minimum scenario with `1` bp one-way slippage and
`$0.005/share` commission turns the result into a `-$38.26795096` loss. The
IBKR Canada fixed and tiered approximations are worse at one-share size because
minimum commissions dominate. The measured execution cost in the no-minimum
scenario, about `$0.1461` per completed trade, is already far larger than the
gross expectancy of about `$0.0084` per completed trade.

The useful result is not "trade this." The useful result is that both long-only
and symmetric long/short candidates can be expressed through shared strategy
decisions and backtested over the trusted normalized cache with reusable
diagnostics. Next research should add stricter regime filters before any
paper/live validation.

### Next Research Plan

The external deep-research review is saved in
`docs/research/spy-vwap-pullback-deep-research.md`. Its conclusion is to reject
the baseline strategy in its current form and run only one disciplined refinement
cycle to test whether a narrower regime-filtered continuation edge exists.

The next implementation work should focus on research infrastructure before
strategy tuning:

1. Add trade-level analytics: expectancy, median trade PnL, MAE/MFE, holding
   time, drawdown duration, contribution concentration, and daily return
   distribution.
2. Add robustness diagnostics: contribution concentration, chronological splits,
   and simple walk-forward summaries.
3. Add event-day tagging for scheduled macro days before mixing those sessions
   into ordinary-session results.
4. Use the symmetric long/short result as a bridge into the first narrowed
   candidate, `trend-day-vwap-reclaim`, so chop/mixed sessions are filtered
   before adding more entries.

Do not optimize a long list of parameters before these diagnostics exist. The
current gross profit factor of `1.0140` is too close to flat, so broad parameter
search would mostly increase overfitting risk.

## Public Safety

Do not commit `.data/`, real market data files, private account data, credentials,
broker logs, or unsanitized backtest artifacts. Any public sample output should be
framed as engineering validation, not trading performance.
