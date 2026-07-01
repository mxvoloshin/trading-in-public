# Backtesting

The backtesting CLI runs a registered strategy against locally cached,
normalized bars and writes a gitignored JSON summary artifact.

This document explains how to run it. Strategy research notes and result
writeups belong in `docs/research/`, not here.

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

The runner reads project-owned normalized JSONL partitions through
`trade_data.LocalMarketDataStore`. It does not read provider-specific raw
responses directly.

For Alpaca credentials, cache layout, and public-safety rules, see
`docs/market-data.md`.

## Run A Backtest

Run the default registered strategy:

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

Useful options:

- `--quantity`: position size per entry. Default: `1`
- `--cache-dir`: local data root. Default: `.data`
- `--output`: explicit JSON summary path. Default: auto-generated gitignored path
- `--session`: `regular`, `extended`, or `all`

By default, the summary is written to:

```text
.data/backtests/minimal/<strategy>/<instrument>_<timeframe>_<start>_<end>.json
```

Example output fields printed to stdout include:

- `bars_loaded`
- `decisions`
- `approved_orders`
- `fills`
- `pending_orders`
- `ending_position`
- `realized_pnl`
- `unrealized_pnl`
- `total_pnl`
- `closed_trades`
- `win_rate`
- `profit_factor`
- `max_drawdown`
- `output`

## Run With Explicit Costs

Costs are opt-in CLI inputs. Defaults are zero.

```sh
uv run python -m trade_research_app backtest run \
  --strategy close-momentum \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular \
  --quantity 1 \
  --slippage-bps 1 \
  --commission-per-share 0.005 \
  --minimum-commission 1
```

The runner applies one-way slippage at the simulated fill:

- buys are adjusted above the next bar open
- sells are adjusted below the next bar open

Commissions are charged on every simulated fill as:

```text
max(quantity * commission_per_share, minimum_commission)
```

## Run The Standard Cost-Stress Grid

Use the built-in cost-stress command to compare the same strategy and date range
across the standard execution-cost scenarios:

```sh
uv run python -m trade_research_app backtest cost-stress \
  --strategy close-momentum \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular \
  --quantity 1
```

By default, the report is written to:

```text
.data/backtests/cost-stress/<strategy>/<instrument>_<timeframe>_<start>_<end>.json
```

Each scenario row includes compact metrics such as:

- `scenario_name`
- `slippage_bps`
- `commission_per_share`
- `minimum_commission`
- `total_pnl`
- `expectancy_per_trade`
- `profit_factor`
- `total_execution_costs`
- `cost_drag_from_gross`
- `gross_edge_consumed`

## Current Strategy Surface

Backtests select strategies by name with `--strategy`. The active registry is in:

`packages/trade_strategies/src/trade_strategies/registry.py`

The current branch exposes these built-in CLI strategies:

- `close-momentum`
- `spy-opening-range-breakout-trend-hold-midpoint-stop-max-1`

If a strategy is not registered there, it is not runnable from the CLI even if
older research notes mention it.

## Execution Semantics

The runner is responsible for execution, fills, positions, and PnL. Strategies
only emit shared `trade_core.StrategyDecision` records.

Important behavior:

- signals are evaluated on the completed bar
- approved market intents fill at the next bar open
- the runner does not fill at the same close that created the signal
- strategies may request an explicit same-bar exit reference by embedding
  `@price` in the decision reason for stop or forced-flat exits
- realized and unrealized PnL are reported separately
- an open position or unfilled approved order at the end of the window remains
  visible in `ending_position` and `pending_orders`

## Default Run Report

Every backtest summary JSON now includes a compact top-level report contract for
research comparisons:

- `strategy_name`
- `variant_name`
- `trades`
- `long_trades`
- `short_trades`
- `gross_pnl`
- `costed_pnl`
- `profit_factor`
- `expectancy_per_trade`
- `win_rate`
- `average_win`
- `average_loss`
- `max_drawdown`
- `worst_rolling_3_month`
- `worst_rolling_6_month`
- `largest_trade_pct_of_total_pnl`
- `top_5_absolute_trades_pct_of_total_pnl`
- `long_pnl`
- `short_pnl`
- `long_pf`
- `short_pf`
- `long_expectancy`
- `short_expectancy`

The same summary also keeps grouped breakdowns for:

- `year_breakdown`
- `month_breakdown`
- `time_of_day_breakdown`
- `opening_range_pct_breakdown`
- `side_breakdown`
- `exit_type_breakdown`

## Add A Strategy

To add another built-in strategy:

1. Add the strategy module under `packages/trade_strategies/src/trade_strategies/`.
2. Implement the shared `Strategy` interface.
3. Register its factory in `trade_strategies.registry`.
4. Add strategy-specific tests plus a CLI or runner test when orchestration
   behavior changes.

## Public Safety

- Backtest outputs under `.data/` are local artifacts and must not be committed.
- Keep raw result narratives, candidate verdicts, and experiment history in
  `docs/research/`.
- Treat this file as the operator runbook for the backtesting CLI.
