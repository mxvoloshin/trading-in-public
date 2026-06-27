# Trading System Service Map

This document defines the public conceptual service map for Trade in Public. A service here is an architectural responsibility, not necessarily a separately deployed process.

The first implementation may run many responsibilities in one process. The boundaries still matter because they tell future agents where logic belongs.

## Service Map

```text
Market Data
    |
    v
Research / Backtesting <------ Strategy
    |                              |
    v                              v
Analytics / Reporting        Risk / Safety
                                   |
                                   v
Execution / Trading -------> Broker Adapters
        |
        v
Reconciliation
        |
        v
Analytics / Reporting

Operations / Observability surrounds all runtime services.
```

## Research / Backtesting

Purpose:

- validate strategy ideas on historical data
- run experiments and backtests
- produce artifacts that explain assumptions and outcomes

Belongs mostly in:

- `apps/research`
- `packages/trade_strategies`
- `packages/trade_data`
- `packages/trade_analytics`
- shared records from `packages/trade_core`

Must not:

- use a separate copy of live strategy logic
- depend directly on broker wrappers
- silently change semantics that live execution cannot reproduce

## Market Data

Purpose:

- ingest data
- normalize provider-specific data into internal shapes
- define historical and live data boundaries
- handle market sessions and calendar concepts

Belongs mostly in:

- `packages/trade_data`
- shared abstractions from `packages/trade_core`

Must not:

- mix broker execution with data normalization
- leak provider-specific models into strategy logic
- assume one data provider forever

## Strategy

Purpose:

- define reusable decision logic
- produce strategy decisions and signals
- remain reusable across research, paper/live-sim, live execution, and reconciliation

Belongs mostly in:

- `packages/trade_strategies`
- shared domain records from `packages/trade_core`

Must not:

- duplicate logic per app mode
- call broker adapters directly
- hide instrument-specific assumptions inside `trade_core`

## Risk / Safety

Purpose:

- constrain strategy decisions before orders reach execution
- define position sizing boundaries
- enforce daily limits, no-trade windows, and kill-switch concepts
- prevent unknown-state live behavior

Belongs mostly in:

- `packages/trade_core` for generic risk concepts
- strategy or app modules for concrete policy wiring
- execution apps for runtime enforcement

Must not:

- be bypassed by live execution
- exist only in backtests
- rely on undocumented account or broker assumptions

## Execution / Trading

Purpose:

- turn approved order intents into broker submissions
- manage paper/live order lifecycle
- capture broker acknowledgements, status updates, fills, and commissions where available

Belongs mostly in:

- `apps/execution`
- `packages/trade_brokers`
- shared records from `packages/trade_core`

Must not:

- contain independent strategy rules
- contain generic domain rules that belong in `trade_core`
- expose credentials or sensitive account details

## Broker Adapters

Purpose:

- isolate broker-specific APIs, SDKs, authentication/session behavior, and provider quirks
- translate between project-owned domain records and broker-specific request/response models

Belongs mostly in:

- `packages/trade_brokers`

Must not:

- leak broker SDK models into strategy modules
- become the place where strategy decisions are made
- force the entire system to know about one broker wrapper choice

## Reconciliation

Purpose:

- compare planned decisions with actual broker outcomes
- join decisions, order intents, broker orders, fills, fees, realized PnL, slippage, and implementation shortfall
- explain differences between backtest, paper/live-sim, and live results

Belongs mostly in:

- `apps/reconcile`
- `packages/trade_analytics`
- shared identifiers and records from `packages/trade_core`

Must not:

- be treated as optional polish
- rely only on current-day broker state
- lose the connection between decision IDs, order IDs, fill IDs, and reports

## Analytics / Reporting

Purpose:

- produce internal and public review artifacts
- summarize backtests, paper/live-sim, live trading, and reconciliation
- make performance claims traceable to source records

Belongs mostly in:

- `packages/trade_analytics`
- `src/content/blog/`
- future public reports

Must not:

- publish sensitive account details
- imply financial advice
- report results that cannot be traced back to underlying artifacts

## Operations / Observability

Purpose:

- logs
- audit trail
- alerts
- runtime health
- failure visibility
- operational review

Belongs across runtime apps, especially:

- `apps/execution`
- `apps/reconcile`
- future deployment/operations docs

Must not:

- be deferred past live-money readiness
- hide failures that affect trading state
- store secrets in code or public docs
