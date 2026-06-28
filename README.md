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
- `docs/architecture/python-trading-system-foundation.md`
- `docs/architecture/service-map.md`
- `docs/architecture/implementation-principles.md`

## Research Decisions

- `docs/research/historical-market-data-source.md`

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

These folders are scaffolded as importable packages only. They should stay behavior-free until later implementation issues define market data, strategy, broker, backtesting, and reconciliation contracts.

Local market data, backtest outputs, credentials, broker exports, and other private artifacts must not be committed.

## Deploy

This site deploys to GitHub Pages through `.github/workflows/deploy.yml`.

Expected public URL:

```text
https://mxvoloshin.github.io/trading-in-public/
```

This is a personal engineering journal. Nothing here is financial advice.
