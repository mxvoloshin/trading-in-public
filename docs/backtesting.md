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
| Realized PnL | `$2.3470` |
| Unrealized PnL | `$0` |
| Total PnL | `$2.3470` |
| Max realized drawdown | `-$18.2102` |
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
| Realized PnL | `-$38.26795096` |
| Total PnL | `-$38.26795096` |
| Max realized drawdown | `-$40.94114950` |

Verdict: this first mechanical VWAP-pullback version is not live-ready. The
gross edge is effectively flat before commissions, spread, slippage, missed
fills, taxes, borrow/margin constraints, and operational risk. A one-share gross
profit of `$2.3470` over `278` completed trades is about `$0.0084` per completed
trade. Even a mild cost scenario with `1` bp one-way slippage and `$0.005/share`
commission turns the result into a `-$38.26795096` loss.

The useful result is not "trade this." The useful result is that the first
candidate can be expressed through shared strategy decisions and backtested over
the trusted normalized cache. Next research should add explicit cost/slippage
modeling, daily performance distribution, time-of-day breakdowns, and stricter
regime filters before any paper/live validation.

## Public Safety

Do not commit `.data/`, real market data files, private account data, credentials,
broker logs, or unsanitized backtest artifacts. Any public sample output should be
framed as engineering validation, not trading performance.
