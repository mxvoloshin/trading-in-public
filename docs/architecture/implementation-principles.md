# Implementation Principles

These are stable public guardrails for future implementation work.

## Keep The Trading System In This Repo

The actual source code, public-safe implementation decisions, and public-safe architecture docs should live in this public repository.

Use package and app boundaries inside the repo instead of splitting research, execution, and reconciliation into unrelated repositories.

## Keep `trade_core` Generic

`trade_core` must remain market-, broker-, and strategy-agnostic.

Do not put these in `trade_core`:

- specific symbols or tickers
- broker-specific concepts
- concrete strategy names
- broker wrapper models
- provider-specific data models

## Do Not Duplicate Strategy Logic

Strategy logic must not be rewritten separately for backtesting, paper/live-sim, and live execution.

The same strategy definitions should be reusable across modes, with environment-specific behavior supplied by data, broker, execution, or reporting adapters.

## Keep Broker Code Behind Adapters

Broker-specific code belongs in `trade_brokers`.

Strategy modules, analytics modules, and core domain modules should not depend directly on broker SDK or wrapper types.

## Keep Market And Instrument Specifics Out Of Core

Specific markets, indexes, ETFs, and instruments belong in:

- config
- strategy modules
- data adapters
- broker adapters
- reports

They do not belong in generic domain records.

## Own The Core, Rent The Edges

Prefer project-owned code for trading-domain behavior:

- signals
- strategy decisions
- order intents
- positions
- risk rules
- session concepts
- reconciliation joins

Use dependencies for heavy or proven infrastructure:

- test tooling
- linting/formatting
- type checking
- broker SDKs or wrappers
- data-frame/time-series libraries when justified

Avoid tiny convenience packages unless they remove meaningful complexity.

Current runtime dependencies with explicit reasons:

- `httpx` in `packages/trade_data`: direct Alpaca historical market data HTTP integration. The dependency is isolated behind the `trade_data` provider boundary and keeps request construction, error handling, and offline transport tests clean.

## Document Runtime Dependencies

Every runtime dependency must have a clear reason.

When adding a dependency, document:

- what problem it solves
- why project-owned code is not preferred for that problem
- whether it is isolated behind an adapter
- what parts of the codebase may import it

## Preserve Traceability

Every trade decision should be traceable later through stable identifiers.

The architecture should support joins between:

- strategy decision
- signal
- order intent
- broker order
- fill
- commission or fee record
- position/PnL impact
- reconciliation report

Do not design flows that lose this chain.

## Treat Reconciliation As First-Class

Reconciliation is part of the trading system, not a later reporting luxury.

Paper/live-sim and live trading do not behave identically. The system must be able to compare planned behavior with actual broker outcomes.

## Protect Sensitive Information

Do not commit or publish:

- credentials
- account identifiers
- access tokens
- raw account screenshots
- private financial details
- unsanitized broker exports
- private deployment details

Public reports must be sanitized.

## Update Docs With Architecture Changes

If implementation changes a boundary, package responsibility, service definition, dependency rule, or agent workflow, update the relevant architecture docs in the same pull request.

## Review Questions For Future Agents

Before opening an implementation PR, check:

- Did I read `AGENTS.md` and the architecture docs?
- Did I keep core domain code generic?
- Did I avoid duplicating strategy logic across modes?
- Did I keep broker/data provider specifics behind boundaries?
- Did I avoid unnecessary dependencies?
- Did I preserve decision-to-fill traceability?
- Did I update docs if I changed architecture behavior?
