from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trade_core import DecisionAction, InstrumentRef, StrategyInputRef, StrategyRunId
from trade_data import Bar
from trade_strategies import CloseMomentumStrategy, StrategyDecisionContext, get_strategy


def test_close_momentum_strategy_emits_shared_strategy_decisions() -> None:
    strategy = CloseMomentumStrategy()
    run_id = StrategyRunId("test-run")
    previous_bar = _bar(close=100.0, minute=30)
    current_bar = _bar(close=101.0, minute=35)
    input_ref = StrategyInputRef(
        instrument=InstrumentRef(instrument_id="SPY.US", market="XNYS", currency="USD"),
        timeframe="5Min",
        source="test",
        observed_at_utc=current_bar.timestamp_utc,
    )

    decision = strategy.decide(
        bar=current_bar,
        context=StrategyDecisionContext(
            strategy_run_id=run_id,
            input_ref=input_ref,
            sequence_number=2,
            previous_bar=previous_bar,
            position_quantity=Decimal("0"),
        ),
    )

    assert decision.action == DecisionAction.ENTER_LONG
    assert decision.strategy_run_id == run_id
    assert decision.input_refs == (input_ref,)
    assert decision.decided_at_utc == input_ref.observed_at_utc
    assert decision.strategy_decision_id.value == "test-run-strategy-decision-0002"


def test_strategy_registry_returns_built_in_strategies_by_name() -> None:
    strategy = get_strategy("close-momentum")

    assert strategy.name == "close-momentum"


def _bar(*, close: float, minute: int) -> Bar:
    return Bar(
        instrument_id="SPY.US",
        timeframe="5Min",
        timestamp_utc=datetime(2026, 6, 26, 13, minute, tzinfo=UTC),
        open=close,
        high=close,
        low=close,
        close=close,
        volume=1_000,
        session="regular",
    )
