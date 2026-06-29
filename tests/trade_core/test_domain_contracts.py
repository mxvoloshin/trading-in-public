from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from trade_core import (
    DecisionAction,
    InstrumentRef,
    OrderIntent,
    OrderSide,
    OrderType,
    RiskDecision,
    RiskOutcome,
    Signal,
    SignalDirection,
    SignalId,
    StrategyDecision,
    StrategyInputRef,
    StrategyRunId,
)


def test_shared_contracts_preserve_decision_to_intent_traceability() -> None:
    run_id = StrategyRunId.new("run")
    instrument = InstrumentRef(instrument_id="SPY.US", market="XNYS", currency="USD")
    input_ref = StrategyInputRef(
        instrument=instrument,
        timeframe="5Min",
        source="alpaca",
        observed_at_utc=datetime(2026, 6, 26, 19, 55, tzinfo=UTC),
    )
    decision = StrategyDecision(
        strategy_run_id=run_id,
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

    assert decision.strategy_run_id == run_id
    assert risk_decision.strategy_decision_id == decision.strategy_decision_id
    assert order_intent.strategy_decision_id == decision.strategy_decision_id
    assert order_intent.risk_decision_id == risk_decision.risk_decision_id
    assert risk_decision.outcome == RiskOutcome.APPROVED


def test_risk_decision_can_record_modified_strategy_decisions() -> None:
    decision = StrategyDecision(
        strategy_run_id=StrategyRunId.new("run"),
        strategy_name="opening-range-breakout",
        action=DecisionAction.ENTER_LONG,
        input_refs=(),
        reason="test",
        decided_at_utc=datetime(2026, 6, 26, 20, 0, tzinfo=UTC),
    )

    risk_decision = RiskDecision.modified(
        strategy_decision_id=decision.strategy_decision_id,
        decided_at_utc=datetime(2026, 6, 26, 20, 0, 1, tzinfo=UTC),
        reason="reduced_size_to_limit",
    )

    assert risk_decision.outcome == RiskOutcome.MODIFIED
    assert risk_decision.strategy_decision_id == decision.strategy_decision_id


def test_core_contracts_require_timezone_aware_timestamps() -> None:
    instrument = InstrumentRef(instrument_id="SPY.US", market="XNYS", currency="USD")

    with pytest.raises(ValueError, match="timezone"):
        StrategyInputRef(
            instrument=instrument,
            timeframe="5Min",
            source="alpaca",
            observed_at_utc=datetime(2026, 6, 26, 19, 55),
        )


def test_strategy_decisions_can_reference_optional_signals() -> None:
    run_id = StrategyRunId.new("run")
    instrument = InstrumentRef(instrument_id="SPY.US", market="XNYS", currency="USD")
    signal = Signal(
        strategy_run_id=run_id,
        instrument=instrument,
        direction=SignalDirection.LONG,
        reason="momentum_confirmed",
        generated_at_utc=datetime(2026, 6, 26, 20, 0, tzinfo=UTC),
    )
    decision = StrategyDecision(
        strategy_run_id=run_id,
        strategy_name="opening-range-breakout",
        action=DecisionAction.ENTER_LONG,
        input_refs=(),
        reason="signal_confirmed",
        decided_at_utc=datetime(2026, 6, 26, 20, 1, tzinfo=UTC),
        signal_ids=(signal.signal_id,),
    )

    assert decision.signal_ids == (signal.signal_id,)


def test_order_intent_rejects_invalid_order_shape() -> None:
    instrument = InstrumentRef(instrument_id="SPY.US", market="XNYS", currency="USD")
    decision = StrategyDecision(
        strategy_run_id=StrategyRunId.new("run"),
        strategy_name="opening-range-breakout",
        action=DecisionAction.ENTER_LONG,
        input_refs=(),
        reason="test",
        decided_at_utc=datetime(2026, 6, 26, 20, 0, tzinfo=UTC),
    )
    risk_decision = RiskDecision.approved(
        strategy_decision_id=decision.strategy_decision_id,
        decided_at_utc=datetime(2026, 6, 26, 20, 0, 1, tzinfo=UTC),
        reason="test",
    )

    with pytest.raises(ValueError, match="quantity"):
        OrderIntent(
            strategy_decision_id=decision.strategy_decision_id,
            risk_decision_id=risk_decision.risk_decision_id,
            instrument=instrument,
            side=OrderSide.BUY,
            quantity=Decimal("0"),
            order_type=OrderType.MARKET,
            created_at_utc=datetime(2026, 6, 26, 20, 0, 2, tzinfo=UTC),
            reason="test",
        )

    with pytest.raises(ValueError, match="limit_price"):
        OrderIntent(
            strategy_decision_id=decision.strategy_decision_id,
            risk_decision_id=risk_decision.risk_decision_id,
            instrument=instrument,
            side=OrderSide.BUY,
            quantity=Decimal("10"),
            order_type=OrderType.LIMIT,
            created_at_utc=datetime(2026, 6, 26, 20, 0, 2, tzinfo=UTC),
            reason="test",
        )


def test_traceability_ids_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SignalId("")
