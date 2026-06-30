from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trade_core import (
    DecisionAction,
    InstrumentRef,
    StrategyDecision,
    StrategyInputRef,
    StrategyRunId,
)
from trade_data import Bar
from trade_strategies import (
    SpyVwapPullbackStrategy,
    StrategyDecisionContext,
    SymmetricSpyVwapPullbackStrategy,
    get_strategy,
)


def test_spy_vwap_pullback_enters_after_pullback_and_trend_resumption() -> None:
    strategy = SpyVwapPullbackStrategy()
    bars = (
        _bar(index=0, open=100.0, high=101.0, low=99.0, close=100.0),
        _bar(index=1, open=100.0, high=101.5, low=100.0, close=101.0),
        _bar(index=2, open=101.0, high=102.5, low=101.0, close=102.0),
        _bar(index=3, open=102.0, high=103.5, low=102.0, close=103.0),
        _bar(index=4, open=103.0, high=104.5, low=103.0, close=104.0),
        _bar(index=5, open=104.0, high=105.5, low=104.0, close=105.0),
        _bar(index=6, open=104.0, high=104.0, low=102.6, close=103.0),
        _bar(index=7, open=103.5, high=105.2, low=103.5, close=105.0),
    )

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == "spy-vwap-pullback"
    assert "vwap_pullback_resumed_above_opening_range" in decisions[-1].reason


def test_spy_vwap_pullback_exits_when_close_loses_vwap() -> None:
    strategy = SpyVwapPullbackStrategy()
    setup_bars = (
        _bar(index=0, open=100.0, high=101.0, low=99.0, close=100.0),
        _bar(index=1, open=100.0, high=101.5, low=100.0, close=101.0),
        _bar(index=2, open=101.0, high=102.5, low=101.0, close=102.0),
        _bar(index=3, open=102.0, high=103.5, low=102.0, close=103.0),
        _bar(index=4, open=103.0, high=104.5, low=103.0, close=104.0),
        _bar(index=5, open=104.0, high=105.5, low=104.0, close=105.0),
        _bar(index=6, open=104.0, high=104.0, low=102.6, close=103.0),
        _bar(index=7, open=103.5, high=105.2, low=103.5, close=105.0),
    )
    _decisions_for_bars(strategy, setup_bars, position_quantity=Decimal("0"))

    exit_bar = _bar(index=8, open=104.0, high=104.0, low=101.0, close=101.0)
    decision = strategy.decide(
        bar=exit_bar,
        context=_context(
            bar=exit_bar,
            sequence_number=9,
            previous_bar=setup_bars[-1],
            position_quantity=Decimal("1"),
        ),
    )

    assert decision.action == DecisionAction.EXIT_LONG
    assert "close_below_vwap" in decision.reason


def test_symmetric_spy_vwap_pullback_enters_short_after_bearish_retest() -> None:
    strategy = SymmetricSpyVwapPullbackStrategy()
    bars = (
        _bar(index=0, open=100.0, high=101.0, low=99.0, close=100.0),
        _bar(index=1, open=100.0, high=100.0, low=98.5, close=99.0),
        _bar(index=2, open=99.0, high=99.0, low=97.5, close=98.0),
        _bar(index=3, open=98.0, high=98.0, low=96.5, close=97.0),
        _bar(index=4, open=97.0, high=97.0, low=95.5, close=96.0),
        _bar(index=5, open=96.0, high=96.0, low=94.5, close=95.0),
        _bar(index=6, open=96.0, high=97.4, low=96.0, close=97.0),
        _bar(index=7, open=96.5, high=96.5, low=94.8, close=95.0),
    )

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_SHORT
    assert decisions[-1].strategy_name == "spy-vwap-pullback-long-short"
    assert "vwap_retest_resumed_below_opening_range" in decisions[-1].reason


def test_symmetric_spy_vwap_pullback_exits_short_when_close_reclaims_vwap() -> None:
    strategy = SymmetricSpyVwapPullbackStrategy()
    setup_bars = (
        _bar(index=0, open=100.0, high=101.0, low=99.0, close=100.0),
        _bar(index=1, open=100.0, high=100.0, low=98.5, close=99.0),
        _bar(index=2, open=99.0, high=99.0, low=97.5, close=98.0),
        _bar(index=3, open=98.0, high=98.0, low=96.5, close=97.0),
        _bar(index=4, open=97.0, high=97.0, low=95.5, close=96.0),
        _bar(index=5, open=96.0, high=96.0, low=94.5, close=95.0),
        _bar(index=6, open=96.0, high=97.4, low=96.0, close=97.0),
        _bar(index=7, open=96.5, high=96.5, low=94.8, close=95.0),
    )
    _decisions_for_bars(strategy, setup_bars, position_quantity=Decimal("0"))

    exit_bar = _bar(index=8, open=96.0, high=100.0, low=96.0, close=100.0)
    decision = strategy.decide(
        bar=exit_bar,
        context=_context(
            bar=exit_bar,
            sequence_number=9,
            previous_bar=setup_bars[-1],
            position_quantity=Decimal("-1"),
        ),
    )

    assert decision.action == DecisionAction.EXIT_SHORT
    assert "close_above_vwap" in decision.reason


def test_spy_vwap_pullback_respects_max_daily_trades() -> None:
    strategy = SpyVwapPullbackStrategy(max_trades_per_day=1)
    first_setup = (
        _bar(index=0, open=100.0, high=101.0, low=99.0, close=100.0),
        _bar(index=1, open=100.0, high=101.5, low=100.0, close=101.0),
        _bar(index=2, open=101.0, high=102.5, low=101.0, close=102.0),
        _bar(index=3, open=102.0, high=103.5, low=102.0, close=103.0),
        _bar(index=4, open=103.0, high=104.5, low=103.0, close=104.0),
        _bar(index=5, open=104.0, high=105.5, low=104.0, close=105.0),
        _bar(index=6, open=104.0, high=104.0, low=102.6, close=103.0),
        _bar(index=7, open=103.5, high=105.2, low=103.5, close=105.0),
    )
    decisions = _decisions_for_bars(strategy, first_setup, position_quantity=Decimal("0"))
    assert decisions[-1].action == DecisionAction.ENTER_LONG

    second_pullback = _bar(index=8, open=105.0, high=105.1, low=103.4, close=104.0)
    second_resume = _bar(index=9, open=104.2, high=106.2, low=104.2, close=106.0)
    strategy.decide(
        bar=second_pullback,
        context=_context(
            bar=second_pullback,
            sequence_number=9,
            previous_bar=first_setup[-1],
            position_quantity=Decimal("0"),
        ),
    )
    decision = strategy.decide(
        bar=second_resume,
        context=_context(
            bar=second_resume,
            sequence_number=10,
            previous_bar=second_pullback,
            position_quantity=Decimal("0"),
        ),
    )

    assert decision.action == DecisionAction.HOLD
    assert "entry_context_not_ready" in decision.reason


def test_strategy_registry_returns_spy_vwap_pullback() -> None:
    strategy = get_strategy("spy-vwap-pullback")

    assert strategy.name == "spy-vwap-pullback"


def test_strategy_registry_returns_symmetric_spy_vwap_pullback() -> None:
    strategy = get_strategy("spy-vwap-pullback-long-short")

    assert strategy.name == "spy-vwap-pullback-long-short"


def _decisions_for_bars(
    strategy: SpyVwapPullbackStrategy | SymmetricSpyVwapPullbackStrategy,
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
