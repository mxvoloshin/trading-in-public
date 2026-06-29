# Shared Core Boundary Between Backtesting And Live Trading

Date: 2026-06-29

Issue: [#11](https://github.com/mxvoloshin/trading-in-public/issues/11)

## Decision

Use **shared strategy decisions, shared risk decisions, shared order intents, and shared traceability IDs** as the first core boundary between backtesting and live execution.

Do not use one fully shared lifecycle model for orders, statuses, fills, commissions, positions, portfolio snapshots, PnL, or broker recovery state. Backtesting and live trading should model those lifecycle details separately, then map them into reconciliation and analytics records through stable project-owned identifiers.

This means the next core/domain implementation issue should build only the smallest records needed to preserve the decision-to-intent trace:

- strategy input references
- signals, if the first strategy needs an explicit signal record
- strategy decisions
- risk decisions
- order intents
- traceability IDs

It should not build final broker order, execution, commission, position, PnL, or reconciliation contracts yet.

## Decision Summary

- Recommended option: Option 3, **Shared Decisions And Order Intents**.
- Strategy code should be reusable across research, backtesting, paper/live-sim, and live execution.
- Strategy outputs should stop at project-owned decisions and order intents.
- Backtesting should translate order intents into deterministic simulated orders/fills.
- Live execution should translate order intents into broker submissions through `trade_brokers`.
- Broker state should stay broker-informed and mode-specific until real paper-account spikes prove which normalized records are needed.
- Reconciliation and analytics should join mode-specific facts through shared IDs instead of pretending all modes have identical lifecycle semantics.

## Why This Boundary

The project needs reusable strategy logic without forcing live execution into a toy backtest model.

The IBKR research found that live execution has broker-specific lifecycle facts that do not exist in backtesting: TWS or IB Gateway connection state, client IDs, API order IDs, `permId`, `execId`, separate order status/execution/commission events, delayed commission reports, market data subscription modes, and reconnect/recovery behavior ([IBKR API shape research](ibkr-api-shape.md)).

The market-data research and implementation already point in the opposite direction for research inputs: historical bars should be provider-neutral and normalized inside `trade_data`, with Alpaca details hidden behind that package boundary ([historical market data source decision](historical-market-data-source.md)).

So the safest common layer is the part both worlds genuinely share:

1. A strategy receives normalized market inputs and configuration.
2. A strategy produces a decision.
3. Risk policy approves, rejects, or changes that decision.
4. The system records a broker-neutral order intent.
5. Backtest execution or live execution takes over from that intent.

## Architecture Options Compared

### Option 1: Fully Shared Lifecycle Model

Backtesting and live trading use the same records for decisions, order intents, orders, fills, positions, and reconciliation.

Rejected for v1.

Why:

- IBKR order state is event-driven and broker-specific.
- A live order can have separate acknowledgement, status, execution, and commission timelines.
- `permId`, `execId`, API order ID, client ID, reconnect behavior, and open-order recovery rules are live execution facts, not backtest facts.
- Backtests need deterministic simulated fills and portfolio state, not direct copies of broker event streams.
- A single lifecycle model would either hide important live details or overcomplicate early backtests.

### Option 2: Shared Decisions Only

Strategy decision records are shared, while backtesting and live execution use separate models after that point.

Rejected as too thin for the next milestone.

Why:

- The system needs a stable place to express "what we intended to trade" before either simulation or broker submission.
- Reconciliation needs to join a strategy decision to a planned trade shape.
- Without a shared order intent, each mode would invent its own decision-to-order translation and strategy reuse would be weaker.

### Option 3: Shared Decisions And Order Intents

Strategies produce shared decisions. Risk policy produces shared risk decisions. Approved decisions become shared broker-neutral order intents. Backtesting and live execution then branch into separate execution and fill models.

Recommended.

Why:

- It preserves strategy reuse.
- It gives backtests and live execution a shared handoff contract.
- It keeps IBKR status, execution, commission, and account details out of the core strategy boundary.
- It supports decision-to-fill traceability without implementing a false shared lifecycle.
- It is small enough for the next implementation issue.

### Option 4: Separate Models With Explicit Mapping

Backtesting and live trading each have independent models, and mapping records preserve traceability.

Partially accepted after the order-intent boundary.

Why:

- Separate models are right for simulated fills versus broker executions.
- Explicit mapping is right for reconciliation and analytics.
- But using separate models before order intent would make strategy and risk behavior harder to reuse.

## Concept Ownership

| Concept | Boundary Decision | Owner |
| --- | --- | --- |
| Strategy inputs | Shared normalized input references, not raw provider payloads | `trade_data`, `trade_core` for generic references only |
| Market data records | Shared provider-neutral bars for research/backtesting; broker live data remains adapter-local until normalized | `trade_data` |
| Signals | Shared only if useful for the first strategy; otherwise defer | `trade_core` or `trade_strategies` |
| Strategy decisions | Shared | `trade_core` |
| Risk decisions | Shared | `trade_core` |
| Order intents | Shared broker-neutral intent | `trade_core` |
| Orders | Separate simulated order and broker order records | `apps/research`, `apps/execution`, `trade_brokers` |
| Order statuses | Separate simulated status and broker-informed status | `apps/research`, `trade_brokers`, `apps/execution` |
| Fills/executions | Separate simulated fills and broker executions; map later for reporting | `apps/research`, `trade_brokers`, `apps/execution` |
| Commissions/fees | Separate assumptions and broker commission reports; common analytics view later | `apps/research`, `trade_brokers`, `trade_analytics` |
| Positions | Separate simulated positions and broker-reported positions | `apps/research`, `trade_brokers`, `apps/reconcile` |
| Portfolio/account snapshots | Separate simulated portfolio and broker account snapshots | `apps/research`, `trade_brokers`, `apps/reconcile` |
| PnL records | Mode-specific source records, common reporting summaries later | `trade_analytics` |
| Reconciliation records | Deferred until execution facts exist; must join shared IDs to mode-specific facts | `apps/reconcile`, `trade_analytics` |
| Traceability IDs | Shared | `trade_core` |
| Analytics/reporting records | Shared reporting views after mapping, not core lifecycle records | `trade_analytics` |

## Package Ownership

### `trade_core`

Should own:

- project-owned IDs for decisions, risk decisions, order intents, and downstream correlation
- generic instrument references that do not encode one provider or broker
- signal records if the first strategy needs them
- strategy decision records
- risk decision records
- broker-neutral order intent records
- small enums/value objects that are not broker-, provider-, or strategy-specific

Should not own yet:

- broker orders
- IBKR statuses
- simulated fills
- broker executions
- commission reports
- account snapshots
- position/PnL models
- reconciliation result records

### `trade_data`

Should own:

- provider-neutral historical bar records
- provider/source interfaces
- source request shapes
- normalization from provider payloads into project bars
- market sessions and calendar behavior needed by data loading

Should not own:

- strategy decisions
- order intents
- broker order lifecycle
- live account state

### `trade_brokers`

Should own:

- IBKR adapter code and dependencies such as `ib_async`
- broker connection/session behavior
- broker request/response mapping
- broker order IDs, `permId`, `execId`, request IDs, and ticker IDs
- broker-specific order statuses, execution events, and commission reports
- redaction rules for broker/account facts when those integrations are added

Should expose only project-owned records across the adapter boundary.

### `trade_strategies`

Should own:

- strategy-specific parameters
- feature calculations
- entry/exit rules
- strategy modules that create shared strategy decisions

Should not own:

- broker adapters
- app orchestration
- generic order lifecycle records

### `trade_analytics`

Should own:

- backtest summaries
- reconciliation summaries
- reporting views that join decisions, order intents, simulated outcomes, broker outcomes, and fees
- public-safe report helpers

Should not become the source of truth for broker state or strategy behavior.

### `apps/research`

Should own:

- backtest orchestration
- translation from shared order intents into simulated orders/fills
- simulated portfolio state
- local research artifacts

### `apps/execution`

Should own:

- paper/live orchestration
- translation from approved order intents into broker adapter calls
- runtime health and readiness checks
- order status and execution event capture

### `apps/reconcile`

Should own:

- planned-versus-actual joins
- comparison of strategy decisions, order intents, simulated outcomes, broker outcomes, commissions, positions, and PnL
- public-safe reconciliation outputs

## What Must Be Traceable

The system should preserve this chain, even if later links are represented differently in backtests and live execution:

```text
strategy_run_id
  -> strategy_decision_id
  -> risk_decision_id
  -> order_intent_id
  -> simulated_order_id or broker_submission_id
  -> simulated_fill_id or broker_execution_id
  -> commission_or_fee_record_id
  -> reconciliation_record_id
  -> analytics_report_id
```

For v1 implementation, only the first four IDs need to be core concepts. Later IDs should be introduced when the corresponding runner, broker adapter, or reconciliation issue exists.

## What Should Be Broker-Specific

These should remain hidden behind `trade_brokers` and execution app boundaries:

- TWS or IB Gateway connection readiness
- socket host, port, and client ID
- `ib_async`, `ib_insync`, or raw `ibapi` objects
- IBKR `Contract`, `Order`, and `Trade` objects
- API order ID sequencing
- `permId`
- `execId`
- request/ticker IDs
- raw order status strings
- raw execution and commission report payloads
- account summary tags and account IDs
- live/delayed market data mode
- pacing, line limits, reconnect, and resubscribe behavior

Broker-specific facts may be persisted by broker/execution code, but they should not become strategy-facing or backtest-facing core fields.

## What Should Be Strategy-Owned

Strategies should own:

- the market inputs they require
- parameter names and defaults
- signal calculations
- entry/exit conditions
- the reason text or reason codes behind a decision
- strategy-specific risk hints when needed

Strategies should not own:

- broker order IDs
- provider request fields
- fill simulation mechanics
- live execution retry logic
- account snapshot parsing
- public/private logging rules

## Follow-Up Implementation Direction

Issue [#12](https://github.com/mxvoloshin/trading-in-public/issues/12) should define selected core/domain contracts for:

- `StrategyRunId`
- `StrategyDecisionId`
- `RiskDecisionId`
- `OrderIntentId`
- instrument reference
- strategy input reference
- optional signal record
- strategy decision
- risk decision
- order intent

Issue #12 should not define:

- final order lifecycle
- broker status model
- fill/execution model
- commission model
- position model
- portfolio/account model
- PnL model
- reconciliation model

Those should be created later when the first backtest runner, IBKR paper spike, execution persistence design, and reconciliation flow provide real evidence.

## Public Safety

This decision document intentionally does not include:

- private account identifiers
- real or paper order IDs
- broker screenshots
- raw API responses
- credentials
- private host/port/client ID values
- balances, holdings, buying power, margin, or account state

Future examples should keep the same boundary: project-owned IDs and synthetic data are safe; broker/account facts need redaction or must stay local.

