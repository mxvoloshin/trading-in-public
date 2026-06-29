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

## Public Safety

Do not commit `.data/`, real market data files, private account data, credentials,
broker logs, or unsanitized backtest artifacts. Any public sample output should be
framed as engineering validation, not trading performance.
