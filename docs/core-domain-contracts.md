# Core Domain Contracts

Issue: [#12](https://github.com/mxvoloshin/trading-in-public/issues/12)

The first `trade_core` contracts implement the current shared boundary for
research and future execution.

They intentionally cover only:

- strategy input references
- optional strategy signals
- strategy decisions
- risk decisions
- broker-neutral order intents
- traceability IDs

The current boundary rule is:

- share strategy decisions
- share risk decisions
- share broker-neutral order intents
- keep simulated fills and broker execution records mode-specific

They do not model broker orders, order statuses, fills, executions, commissions, positions, portfolio snapshots, PnL, reconciliation records, or analytics reports.

## Traceability Shape

The implemented v1 chain is:

```text
StrategyRunId
  -> StrategyDecisionId
  -> RiskDecisionId
  -> OrderIntentId
```

Later backtest, execution, broker, and reconciliation issues should attach their own mode-specific IDs after `OrderIntentId`.

## Example

```python
from datetime import UTC, datetime
from decimal import Decimal

from trade_core import (
    DecisionAction,
    InstrumentRef,
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecision,
    StrategyDecision,
    StrategyInputRef,
    StrategyRunId,
)

instrument = InstrumentRef(
    instrument_id="SPY.US",
    market="XNYS",
    currency="USD",
)
input_ref = StrategyInputRef(
    instrument=instrument,
    timeframe="5Min",
    source="alpaca",
    observed_at_utc=datetime(2026, 6, 26, 19, 55, tzinfo=UTC),
)
decision = StrategyDecision(
    strategy_run_id=StrategyRunId.new(),
    strategy_name="opening-range-breakout",
    action=DecisionAction.ENTER_LONG,
    input_refs=(input_ref,),
    reason="breakout_above_range",
    decided_at_utc=datetime(2026, 6, 26, 20, 0, tzinfo=UTC),
)
risk_decision = RiskDecision.approved(
    strategy_decision_id=decision.strategy_decision_id,
    decided_at_utc=datetime(2026, 6, 26, 20, 0, 1, tzinfo=UTC),
    reason="within_position_limits",
)
order_intent = OrderIntent(
    strategy_decision_id=decision.strategy_decision_id,
    risk_decision_id=risk_decision.risk_decision_id,
    instrument=instrument,
    side=OrderSide.BUY,
    quantity=Decimal("10"),
    order_type=OrderType.MARKET,
    created_at_utc=datetime(2026, 6, 26, 20, 0, 2, tzinfo=UTC),
    reason="approved_breakout_entry",
)
```

## Contract Rules

- Timestamps must be timezone-aware. Contracts normalize them to UTC.
- `InstrumentRef` uses project-owned IDs such as `SPY.US`, not provider symbols or broker contract IDs.
- `StrategyInputRef.source` names the normalized source boundary, such as `alpaca`, not a raw payload location.
- `StrategyDecision` records what the strategy wanted to do and why.
- `RiskDecision` records whether risk policy approved, modified, or rejected that decision.
- `OrderIntent` records a broker-neutral trade intent after risk approval or modification.
- `OrderIntent` validates basic order shape: positive quantity, required limit price for limit intents, and required stop price for stop intents.

## Public Safety

These records are safe for public tests and synthetic examples when they use synthetic IDs and market data references.

Do not store real broker account IDs, API order IDs, `permId`, `execId`, raw broker payloads, balances, holdings, or private account state in these contracts.
