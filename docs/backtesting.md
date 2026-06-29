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
  --minimum-commission 0
```

The runner applies slippage one way: buy fills are adjusted above the next bar
open and sell fills are adjusted below the next bar open. Commissions are charged
on every simulated fill as `max(quantity * commission_per_share,
minimum_commission)`. Defaults are zero so gross and cost-adjusted runs are
deliberate and reproducible.

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

Mild cost scenario:

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

Verdict: this first mechanical VWAP-pullback version is not live-ready. The
gross edge is effectively flat before commissions, spread, slippage, missed
fills, taxes, borrow/margin constraints, and operational risk. A one-share gross
profit of `$2.3470` over `278` completed trades is about `$0.0084` per completed
trade. Even a mild cost scenario with `1` bp one-way slippage and `$0.005/share`
commission turns the result into a `-$38.26795096` loss. The measured execution
cost of about `$0.1461` per completed trade is far larger than the gross
expectancy of about `$0.0084` per completed trade.

The useful result is not "trade this." The useful result is that the first
candidate can be expressed through shared strategy decisions and backtested over
the trusted normalized cache with reusable diagnostics. Next research should add
stricter regime filters before any paper/live validation.

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
2. Add execution stress reporting: one-way slippage grids, commission scenarios,
   gross edge consumed by costs, and adverse-selection checks after fills.
3. Add robustness diagnostics: contribution concentration, chronological splits,
   and simple walk-forward summaries.
4. Add event-day tagging for scheduled macro days before mixing those sessions
   into ordinary-session results.
5. Implement the first narrowed candidate, `trend-day-vwap-reclaim`, through the
   existing strategy registry so it can be compared against
   `spy-vwap-pullback` with identical execution semantics.

Do not optimize a long list of parameters before these diagnostics exist. The
current gross profit factor of `1.0140` is too close to flat, so broad parameter
search would mostly increase overfitting risk.

## Public Safety

Do not commit `.data/`, real market data files, private account data, credentials,
broker logs, or unsanitized backtest artifacts. Any public sample output should be
framed as engineering validation, not trading performance.
