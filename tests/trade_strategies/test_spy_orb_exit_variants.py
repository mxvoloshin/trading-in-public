from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from trade_core import (
    DecisionAction,
    InstrumentRef,
    StrategyDecision,
    StrategyInputRef,
    StrategyRunId,
)
from trade_data import Bar
from trade_strategies import (
    SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy,
    SpyOrbAtrTrail1_0Strategy,
    SpyOrbAtrTrail1_5Strategy,
    SpyOrbAtrTrail2_0Strategy,
    SpyOrbBreakEvenAfter1RStrategy,
    SpyOrbStructureTrailStrategy,
    Strategy,
    StrategyDecisionContext,
)


def test_break_even_variant_moves_stop_to_entry_after_one_r() -> None:
    strategy = _ExposedBreakEvenStrategy()
    bar = _bar(index=8, open=100.5, high=101.2, low=100.2, close=101.0)

    action, reason, state = strategy.open_long_decision(
        bar=bar,
        active_stop=Decimal("99"),
        entry_price=Decimal("100"),
        opening_range_mid=Decimal("99"),
        reached_1r=False,
    )

    assert action == DecisionAction.HOLD
    assert reason == "holding_long_breakout"
    assert state.reached_1r is True
    assert state.active_stop == Decimal("100")


def test_atr_trail_variant_ratchets_long_stop() -> None:
    strategy = _ExposedAtrTrailStrategy()
    bar = _bar(index=14, open=104.8, high=105.0, low=104.6, close=104.9)

    action, reason, state = strategy.open_long_decision(
        bar=bar,
        active_stop=Decimal("100"),
        session_bars=[
            _bar(
                index=index,
                open=100.0,
                high=101.0,
                low=100.0,
                close=100.5,
            )
            for index in range(14)
        ],
    )

    assert action == DecisionAction.HOLD
    assert reason == "holding_long_breakout"
    assert state.active_stop == Decimal("104")


def test_structure_trail_variant_activates_after_one_r() -> None:
    strategy = _ExposedStructureTrailStrategy()
    bar = _bar(index=8, open=100.9, high=101.3, low=100.8, close=101.1)

    action, reason, state = strategy.open_long_decision(
        bar=bar,
        active_stop=Decimal("99"),
        entry_price=Decimal("100"),
        opening_range_mid=Decimal("99"),
        reached_1r=False,
        session_bars=[
            _bar(index=5, open=100.0, high=100.7, low=100.2, close=100.5),
            _bar(index=6, open=100.5, high=100.9, low=100.6, close=100.8),
            _bar(index=7, open=100.8, high=101.0, low=100.7, close=100.9),
        ],
    )

    assert action == DecisionAction.HOLD
    assert reason == "holding_long_breakout"
    assert state.reached_1r is True
    assert state.active_stop == Decimal("100.2")


def test_exit_variants_match_baseline_long_entry_decision() -> None:
    bars = _orb_long_entry_setup_bars()
    baseline_decision = _decisions_for_bars(
        SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy(),
        bars,
        position_quantity=Decimal("0"),
    )[-1]

    for strategy in _orb_variants():
        decision = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))[-1]
        assert decision.action == baseline_decision.action
        assert decision.reason == baseline_decision.reason


def test_exit_variants_match_baseline_short_entry_decision() -> None:
    bars = _orb_short_entry_setup_bars()
    baseline_decision = _decisions_for_bars(
        SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy(),
        bars,
        position_quantity=Decimal("0"),
    )[-1]

    for strategy in _orb_variants():
        decision = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))[-1]
        assert decision.action == baseline_decision.action
        assert decision.reason == baseline_decision.reason


def _orb_variants() -> tuple[Strategy, ...]:
    return (
        SpyOrbBreakEvenAfter1RStrategy(),
        SpyOrbAtrTrail1_0Strategy(),
        SpyOrbAtrTrail1_5Strategy(),
        SpyOrbAtrTrail2_0Strategy(),
        SpyOrbStructureTrailStrategy(),
    )


class _ExposedBreakEvenStrategy(SpyOrbBreakEvenAfter1RStrategy):
    def open_long_decision(
        self,
        *,
        bar: Bar,
        active_stop: Decimal,
        entry_price: Decimal,
        opening_range_mid: Decimal,
        reached_1r: bool,
    ) -> tuple[DecisionAction, str, Any]:
        state = self._state_for_bar(bar)
        state.active_stop = active_stop
        state.entry_price = entry_price
        state.opening_range_mid = opening_range_mid
        state.reached_1r = reached_1r
        action, reason = self._open_long_decision(
            state=state,
            bar=bar,
            local_time=bar.timestamp_utc.time(),
        )
        return action, reason, state


class _ExposedAtrTrailStrategy(SpyOrbAtrTrail1_0Strategy):
    def open_long_decision(
        self,
        *,
        bar: Bar,
        active_stop: Decimal,
        session_bars: list[Bar],
    ) -> tuple[DecisionAction, str, Any]:
        state = self._state_for_bar(bar)
        state.active_stop = active_stop
        state.session_bars = session_bars
        action, reason = self._open_long_decision(
            state=state,
            bar=bar,
            local_time=bar.timestamp_utc.time(),
        )
        return action, reason, state


class _ExposedStructureTrailStrategy(SpyOrbStructureTrailStrategy):
    def open_long_decision(
        self,
        *,
        bar: Bar,
        active_stop: Decimal,
        entry_price: Decimal,
        opening_range_mid: Decimal,
        reached_1r: bool,
        session_bars: list[Bar],
    ) -> tuple[DecisionAction, str, Any]:
        state = self._state_for_bar(bar)
        state.active_stop = active_stop
        state.entry_price = entry_price
        state.opening_range_mid = opening_range_mid
        state.reached_1r = reached_1r
        state.session_bars = session_bars
        action, reason = self._open_long_decision(
            state=state,
            bar=bar,
            local_time=bar.timestamp_utc.time(),
        )
        return action, reason, state


def _orb_long_entry_setup_bars() -> tuple[Bar, ...]:
    return (
        _bar(index=0, open=100.0, high=100.4, low=99.9, close=100.1),
        _bar(index=1, open=100.1, high=100.5, low=100.0, close=100.2),
        _bar(index=2, open=100.2, high=100.6, low=100.1, close=100.3),
        _bar(index=3, open=100.3, high=100.7, low=100.2, close=100.4),
        _bar(index=4, open=100.4, high=100.8, low=100.3, close=100.5),
        _bar(index=5, open=100.5, high=100.9, low=100.4, close=100.6),
        _bar(index=6, open=100.6, high=101.2, low=100.5, close=101.1),
    )


def _orb_short_entry_setup_bars() -> tuple[Bar, ...]:
    return (
        _bar(index=0, open=100.0, high=100.4, low=99.9, close=100.1),
        _bar(index=1, open=100.1, high=100.3, low=99.8, close=100.0),
        _bar(index=2, open=100.0, high=100.1, low=99.5, close=99.7),
        _bar(index=3, open=99.7, high=99.8, low=99.3, close=99.5),
        _bar(index=4, open=99.5, high=99.6, low=99.1, close=99.3),
        _bar(index=5, open=99.3, high=99.4, low=98.9, close=99.1),
        _bar(index=6, open=99.1, high=99.2, low=98.4, close=98.6),
    )


def _decisions_for_bars(
    strategy: Strategy,
    bars: tuple[Bar, ...],
    *,
    position_quantity: Decimal,
) -> list[StrategyDecision]:
    decisions: list[StrategyDecision] = []
    previous_bar = None
    for sequence_number, bar in enumerate(bars, start=1):
        decision = strategy.decide(
            bar=bar,
            context=_context(
                bar=bar,
                sequence_number=sequence_number,
                previous_bar=previous_bar,
                position_quantity=position_quantity,
            ),
        )
        decisions.append(decision)
        previous_bar = bar
    return decisions


def _context(
    *,
    bar: Bar,
    sequence_number: int,
    previous_bar: Bar | None,
    position_quantity: Decimal,
) -> StrategyDecisionContext:
    input_ref = StrategyInputRef(
        instrument=InstrumentRef(instrument_id="SPY.US", market="XNYS", currency="USD"),
        timeframe="5Min",
        source="test",
        observed_at_utc=bar.timestamp_utc + timedelta(minutes=5),
    )
    return StrategyDecisionContext(
        strategy_run_id=StrategyRunId("test-run"),
        input_ref=input_ref,
        sequence_number=sequence_number,
        previous_bar=previous_bar,
        position_quantity=position_quantity,
        average_entry_price=Decimal("0"),
    )


def _bar(
    *,
    index: int,
    open: float,
    high: float,
    low: float,
    close: float,
) -> Bar:
    return Bar(
        instrument_id="SPY.US",
        timeframe="5Min",
        timestamp_utc=datetime(2026, 6, 26, 13, 30, tzinfo=UTC) + timedelta(minutes=index * 5),
        open=open,
        high=high,
        low=low,
        close=close,
        volume=1_000,
        session="regular",
    )
