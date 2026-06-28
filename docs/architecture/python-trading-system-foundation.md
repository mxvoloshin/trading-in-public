# Python Trading System Foundation

This document defines the public-safe foundation for the Trade in Public trading system. It is intended for future implementation agents and readers who want to understand the system shape before code exists.

This is an engineering and learning project, not financial advice.

## Foundation Goal

Build one Python codebase that can support:

- strategy research
- historical backtesting
- paper/live-sim validation
- live execution after safety gates
- broker integration through adapters
- planned-versus-actual reconciliation
- analytics and public reporting
- future multi-strategy and multi-market expansion

The foundation should keep strategy logic reusable across research, paper/live-sim, live execution, and reconciliation. A strategy should not have to be rewritten for each mode.

## Repository Direction

Keep the actual trading system code in this public repo.

Use a monorepo-style Python workspace with shared packages and separate app entrypoints or modes.

Planned shape:

```text
packages/
  trade_core/
  trade_strategies/
  trade_data/
  trade_analytics/
  trade_brokers/

apps/
  research/
  execution/
  reconcile/
```

These names define ownership boundaries. They do not require every folder to be created immediately.

## Package Responsibilities

### `trade_core`

Shared trading-domain model.

Owns generic concepts such as:

- instruments as domain concepts
- market sessions and calendars as abstractions
- signals
- strategy decisions
- order intents
- orders
- fills
- positions
- portfolio state
- risk inputs
- identifiers used across decision, order, fill, and reconciliation flows
- common configuration schemas that are not broker-, market-, or strategy-specific

Must not depend on:

- one specific symbol or market
- one broker
- one broker SDK or wrapper
- one strategy
- one backtesting engine
- one live execution app

### `trade_strategies`

Strategy definitions and decision models.

This package is plural because the system should support multiple strategies over time. The first implementation can focus narrowly, but the structure should not assume one instrument or one strategy forever.

Strategy-specific modules may reference:

- instruments
- markets
- parameter sets
- entry/exit conditions
- strategy-specific feature calculations
- strategy-specific reporting labels

Shared strategy helpers should appear only when duplication exists across real strategies.

### `trade_data`

Market data interfaces, ingestion boundaries, normalization, and local storage abstractions.

This package should separate:

- source-specific data fetching
- normalized internal data shapes
- historical data used for backtests
- live or near-real-time data used by execution
- market calendars and sessions

Broker execution and market data are separate concerns, even when the same provider can supply both.

### `trade_analytics`

Metrics, reports, and analysis helpers.

Owns:

- backtest metrics
- drawdown and risk summaries
- slippage and execution-quality metrics
- reconciliation summaries
- public/internal report helpers

Analytics should consume stable domain records instead of reaching directly into broker adapters or strategy internals.

### `trade_brokers`

Broker adapters.

Broker-specific code belongs here. Broker API details, SDK types, authentication behavior, session behavior, and provider quirks should be isolated behind adapter boundaries.

## App Responsibilities

### `apps/research`

Research and backtesting entrypoint.

Owns workflows for:

- running historical experiments
- validating strategies against historical data
- producing backtest artifacts
- comparing parameter choices
- generating research reports

### `apps/execution`

Paper/live execution entrypoint.

Owns workflows for:

- broker session connection through adapters
- order submission
- order status handling
- execution capture
- commission capture where available
- runtime health
- safety controls required before live trading

This app should use shared domain packages and broker adapters. It should not contain duplicate strategy logic.

### `apps/reconcile`

Planned-versus-actual reconciliation entrypoint.

Owns workflows for joining:

- strategy decisions
- order intents
- broker orders
- fills
- commissions or fees
- realized PnL
- slippage or implementation shortfall
- paper/live differences

Reconciliation is first-class because simulated and live trading do not behave identically.

## Tooling Direction

Use:

- `uv` for environment, dependency, lockfile, and workspace management
- `ruff` for linting and formatting
- `pytest` for tests
- `pyright` for type checking

Planned command surface:

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format .
uv run pyright
```

Future implementation issues may refine command names, but they should preserve a small, predictable command surface.

## Multi-Market And Multi-Strategy Readiness

The first strategy can be narrow. The foundation must still support future instruments, markets, and strategy families.

Rules:

- Do not encode one instrument into `trade_core`.
- Do not encode one strategy into app names unless the app is intentionally strategy-specific.
- Keep instruments and markets in config, strategy modules, data adapters, and reports.
- Keep strategy modules easy to add without changing broker or core domain code.

## Public Safety Boundary

Public docs can describe architecture, service boundaries, and process.

Public docs must not expose:

- credentials
- tokens
- account identifiers
- private broker session details
- raw broker statements
- unsanitized order IDs
- deployment details that create security risk
- licensed market data that cannot be redistributed
