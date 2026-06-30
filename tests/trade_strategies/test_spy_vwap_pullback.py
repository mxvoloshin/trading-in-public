from __future__ import annotations

from collections.abc import Sequence
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
    DailyContextVwapReclaimStrategy,
    EntryFilteredTrendDayVwapReclaimStrategy,
    GapAndGoVwapPullbackStrategy,
    SpyVwapPullbackStrategy,
    StrategyDecisionContext,
    SymmetricSpyVwapPullbackStrategy,
    TrendDayVwapReclaimStrategy,
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


def test_trend_day_vwap_reclaim_enters_after_retest_and_reclaim() -> None:
    strategy = TrendDayVwapReclaimStrategy()
    bars = _trend_day_reclaim_setup_bars()

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == "trend-day-vwap-reclaim"
    assert "trend_day_vwap_reclaim" in decisions[-1].reason


def test_trend_day_vwap_reclaim_skips_entries_before_10am() -> None:
    strategy = TrendDayVwapReclaimStrategy()
    bars = _trend_day_reclaim_setup_bars()[:6]

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "entry_context_not_ready" in decisions[-1].reason


def test_trend_day_vwap_reclaim_exits_after_two_closes_below_vwap() -> None:
    strategy = TrendDayVwapReclaimStrategy()
    setup_bars = _trend_day_reclaim_setup_bars()
    _decisions_for_bars(strategy, setup_bars, position_quantity=Decimal("0"))

    first_close_below = _bar(index=8, open=104.0, high=104.5, low=101.5, close=102.5)
    first_decision = strategy.decide(
        bar=first_close_below,
        context=_context(
            bar=first_close_below,
            sequence_number=9,
            previous_bar=setup_bars[-1],
            position_quantity=Decimal("1"),
        ),
    )
    second_close_below = _bar(index=9, open=102.5, high=103.0, low=101.5, close=102.0)
    second_decision = strategy.decide(
        bar=second_close_below,
        context=_context(
            bar=second_close_below,
            sequence_number=10,
            previous_bar=first_close_below,
            position_quantity=Decimal("1"),
        ),
    )

    assert first_decision.action == DecisionAction.HOLD
    assert "first_close_below_vwap" in first_decision.reason
    assert second_decision.action == DecisionAction.EXIT_LONG
    assert "two_closes_below_vwap" in second_decision.reason


def test_trend_day_vwap_reclaim_exits_when_signal_low_fails() -> None:
    strategy = TrendDayVwapReclaimStrategy()
    setup_bars = _trend_day_reclaim_setup_bars()
    _decisions_for_bars(strategy, setup_bars, position_quantity=Decimal("0"))

    exit_bar = _bar(index=8, open=103.0, high=103.5, low=100.5, close=100.8)
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
    assert "close_below_signal_bar_low" in decision.reason


def test_trend_day_vwap_reclaim_allows_only_one_trade_per_day() -> None:
    strategy = TrendDayVwapReclaimStrategy()
    setup_bars = _trend_day_reclaim_setup_bars()
    decisions = _decisions_for_bars(strategy, setup_bars, position_quantity=Decimal("0"))
    assert decisions[-1].action == DecisionAction.ENTER_LONG

    second_retest = _bar(index=8, open=105.0, high=105.2, low=102.0, close=103.0)
    second_reclaim = _bar(index=9, open=103.0, high=106.0, low=102.5, close=106.0)
    strategy.decide(
        bar=second_retest,
        context=_context(
            bar=second_retest,
            sequence_number=9,
            previous_bar=setup_bars[-1],
            position_quantity=Decimal("0"),
        ),
    )
    decision = strategy.decide(
        bar=second_reclaim,
        context=_context(
            bar=second_reclaim,
            sequence_number=10,
            previous_bar=second_retest,
            position_quantity=Decimal("0"),
        ),
    )

    assert decision.action == DecisionAction.HOLD
    assert "entry_context_not_ready" in decision.reason


def test_entry_filtered_trend_day_reclaim_enters_when_entry_time_trend_gate_passes() -> None:
    strategy = EntryFilteredTrendDayVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03")
    )
    bars = _trend_day_reclaim_setup_bars()

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == "trend-day-vwap-reclaim-entry-filter"
    assert "trend_day_vwap_reclaim" in decisions[-1].reason


def test_entry_filtered_trend_day_reclaim_rejects_weak_opening_window() -> None:
    strategy = EntryFilteredTrendDayVwapReclaimStrategy(min_first_30_minute_return=Decimal("0.001"))
    bars = (
        _bar(index=0, open=100.0, high=101.0, low=99.0, close=100.0),
        _bar(index=1, open=100.0, high=101.5, low=100.0, close=100.0),
        _bar(index=2, open=100.0, high=102.5, low=100.0, close=100.0),
        _bar(index=3, open=100.0, high=103.5, low=100.0, close=100.0),
        _bar(index=4, open=100.0, high=104.5, low=100.0, close=100.0),
        _bar(index=5, open=100.0, high=105.5, low=100.0, close=100.0),
        _bar(index=6, open=104.0, high=104.0, low=102.0, close=103.0),
        _bar(index=7, open=103.5, high=105.2, low=101.0, close=105.0),
    )

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "entry_trend_filter_first_30_return_too_weak" in decisions[-1].reason


def test_entry_filtered_trend_day_reclaim_rejects_extended_entries() -> None:
    strategy = EntryFilteredTrendDayVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.001")
    )
    bars = _trend_day_reclaim_setup_bars()

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "entry_trend_filter_entry_too_extended" in decisions[-1].reason


def test_entry_filtered_trend_day_reclaim_rejects_low_opening_participation() -> None:
    strategy = EntryFilteredTrendDayVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
        min_opening_relative_volume=Decimal("1.5"),
        relative_volume_lookback_sessions=1,
    )
    prior_day = tuple(
        _bar(index=index, open=100.0, high=101.0, low=99.0, close=100.0, volume=2_000)
        for index in range(6)
    )
    current_day = _trend_day_reclaim_setup_bars(day=29, volume=1_000)

    _decisions_for_bars(strategy, prior_day, position_quantity=Decimal("0"))
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "entry_trend_filter_opening_participation_too_low" in decisions[-1].reason


def test_gap_and_go_vwap_pullback_enters_when_gap_holds_and_reclaim_sets_up() -> None:
    strategy = GapAndGoVwapPullbackStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
        max_opening_range_pct=Decimal("0.08"),
    )
    prior_day = (_bar(index=0, open=99.0, high=100.0, low=98.0, close=99.6),)
    current_day = _trend_day_reclaim_setup_bars(day=29)

    _decisions_for_bars(strategy, prior_day, position_quantity=Decimal("0"))
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == "gap-and-go-vwap-pullback"
    assert "trend_day_vwap_reclaim" in decisions[-1].reason


def test_gap_and_go_vwap_pullback_rejects_failed_gap_by_10am() -> None:
    strategy = GapAndGoVwapPullbackStrategy(max_entry_distance_from_vwap=Decimal("0.03"))
    prior_day = (_bar(index=0, open=99.0, high=101.0, low=98.0, close=100.5),)
    current_day = (
        _bar(index=0, open=101.0, high=101.5, low=100.0, close=101.0, day=29),
        _bar(index=1, open=101.0, high=101.5, low=100.0, close=101.0, day=29),
        _bar(index=2, open=101.0, high=102.5, low=100.0, close=101.0, day=29),
        _bar(index=3, open=101.0, high=103.5, low=100.0, close=101.0, day=29),
        _bar(index=4, open=101.0, high=104.5, low=100.0, close=101.0, day=29),
        _bar(index=5, open=101.0, high=105.5, low=100.0, close=100.5, day=29),
        _bar(index=6, open=104.0, high=104.0, low=102.0, close=103.0, day=29),
        _bar(index=7, open=103.5, high=105.2, low=101.0, close=105.0, day=29),
    )

    _decisions_for_bars(strategy, prior_day, position_quantity=Decimal("0"))
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "gap_and_go_gap_failed_by_10am" in decisions[-1].reason


def test_gap_and_go_vwap_pullback_rejects_wide_opening_range() -> None:
    strategy = GapAndGoVwapPullbackStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
        max_opening_range_pct=Decimal("0.005"),
    )
    prior_day = (_bar(index=0, open=99.0, high=100.0, low=98.0, close=99.6),)
    current_day = _trend_day_reclaim_setup_bars(day=29)

    _decisions_for_bars(strategy, prior_day, position_quantity=Decimal("0"))
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "gap_and_go_opening_range_too_wide" in decisions[-1].reason


def test_daily_context_vwap_reclaim_enters_when_completed_daily_trend_supports() -> None:
    strategy = DailyContextVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    current_day = _trend_day_reclaim_setup_bars(day=26)
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == "trend-day-vwap-reclaim-v2-daily-context"
    assert "trend_day_vwap_reclaim" in decisions[-1].reason


def test_daily_context_vwap_reclaim_waits_for_enough_completed_daily_history() -> None:
    strategy = DailyContextVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(24)])
    current_day = _trend_day_reclaim_setup_bars(day=26)
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "daily_context_not_ready" in decisions[-1].reason


def test_daily_context_vwap_reclaim_rejects_prior_close_below_daily_sma() -> None:
    strategy = DailyContextVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
    )

    _seed_completed_daily_closes(strategy, closes=[100 + index for index in range(24)] + [90])
    current_day = _trend_day_reclaim_setup_bars(day=26)
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "daily_context_prior_close_below_sma" in decisions[-1].reason


def test_daily_context_vwap_reclaim_rejects_falling_daily_sma() -> None:
    strategy = DailyContextVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
    )

    _seed_completed_daily_closes(
        strategy,
        closes=[
            140,
            140,
            140,
            140,
            140,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            100,
            105,
        ],
    )
    current_day = _trend_day_reclaim_setup_bars(day=26)
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "daily_context_sma_not_rising" in decisions[-1].reason


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


def test_strategy_registry_returns_trend_day_vwap_reclaim() -> None:
    strategy = get_strategy("trend-day-vwap-reclaim")

    assert strategy.name == "trend-day-vwap-reclaim"


def test_strategy_registry_returns_entry_filtered_trend_day_vwap_reclaim() -> None:
    strategy = get_strategy("trend-day-vwap-reclaim-entry-filter")

    assert strategy.name == "trend-day-vwap-reclaim-entry-filter"


def test_strategy_registry_returns_gap_and_go_vwap_pullback() -> None:
    strategy = get_strategy("gap-and-go-vwap-pullback")

    assert strategy.name == "gap-and-go-vwap-pullback"


def test_strategy_registry_returns_daily_context_vwap_reclaim() -> None:
    strategy = get_strategy("trend-day-vwap-reclaim-v2-daily-context")

    assert strategy.name == "trend-day-vwap-reclaim-v2-daily-context"


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


def _trend_day_reclaim_setup_bars(*, day: int = 26, volume: int = 1_000) -> tuple[Bar, ...]:
    return (
        _bar(index=0, open=100.0, high=101.0, low=99.0, close=100.0, day=day, volume=volume),
        _bar(index=1, open=100.0, high=101.5, low=100.0, close=101.0, day=day, volume=volume),
        _bar(index=2, open=101.0, high=102.5, low=101.0, close=102.0, day=day, volume=volume),
        _bar(index=3, open=102.0, high=103.5, low=102.0, close=103.0, day=day, volume=volume),
        _bar(index=4, open=103.0, high=104.5, low=103.0, close=104.0, day=day, volume=volume),
        _bar(index=5, open=104.0, high=105.5, low=104.0, close=105.0, day=day, volume=volume),
        _bar(index=6, open=104.0, high=104.0, low=102.0, close=103.0, day=day, volume=volume),
        _bar(index=7, open=103.5, high=105.2, low=101.0, close=105.0, day=day, volume=volume),
    )


def _seed_completed_daily_closes(
    strategy: DailyContextVwapReclaimStrategy,
    *,
    closes: Sequence[float],
) -> None:
    for day_offset, close in enumerate(closes, start=1):
        bars = (
            _bar(
                index=0,
                open=close - 1,
                high=close + 1,
                low=close - 2,
                close=close,
                day=day_offset,
            ),
        )
        _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))


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
    day: int = 26,
    volume: int = 1_000,
) -> Bar:
    return Bar(
        instrument_id="SPY.US",
        timeframe="5Min",
        timestamp_utc=datetime(2026, 6, day, 13, 30, tzinfo=UTC) + timedelta(minutes=index * 5),
        open=open,
        high=high,
        low=low,
        close=close,
        volume=volume,
        session="regular",
    )
