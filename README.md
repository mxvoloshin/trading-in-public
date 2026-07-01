# Trade in Public

A public build log for designing, validating, and operating an automated trading system as a software project.

## Commands

Site:

```sh
npm install
npm run dev
npm run build
```

Python workspace:

```sh
uv sync
uv run pytest
uv run ruff check .
uv run ruff format .
uv run ruff format --check .
uv run pyright
```

## Architecture

Start here before implementation work:

- `AGENTS.md`
- `docs/core-domain-contracts.md`
- `docs/architecture/python-trading-system-foundation.md`
- `docs/architecture/service-map.md`
- `docs/architecture/implementation-principles.md`

## Research Workflow

- `docs/research-workflow.md`
- `docs/research-artifacts.md`

## Market Data

Prepare local historical bars for research:

```sh
uv run python -m trade_research_app market-data fetch \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular
```

See `docs/market-data.md` for Alpaca credentials, local cache layout, and public safety rules.

## Backtesting

Run a minimal backtest against locally cached normalized bars:

```sh
uv run python -m trade_research_app backtest run \
  --strategy spy-opening-range-breakout-trend-hold-midpoint-stop-max-1 \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-06-28 \
  --end 2026-06-27 \
  --market XNYS \
  --session regular
```

See `docs/backtesting.md` for the current strategy behavior, output location, and
public safety rules.

## Python Workspace

The trading system code lives in a `uv` workspace.

```text
packages/
  trade_core/
  trade_data/
  trade_strategies/
  trade_analytics/
  trade_brokers/

apps/
  research/
  execution/
  reconcile/
```

These folders are importable workspace packages. The active research path lives
mainly in `packages/trade_data`, `packages/trade_strategies`, and
`apps/research`.

Local market data, backtest outputs, credentials, broker exports, and other private artifacts must not be committed.

## Deploy

This site deploys to GitHub Pages through `.github/workflows/deploy.yml`.

Expected public URL:

```text
https://mxvoloshin.github.io/trading-in-public/
```

This is a personal engineering journal. Nothing here is financial advice.
