from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
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
    DynamicVwapDistanceReclaimStrategy,
    EntryFilteredTrendDayVwapReclaimStrategy,
    GapAndGoVwapPullbackStrategy,
    OpeningDriveQualityVwapReclaimStrategy,
    RvolBucketVwapReclaimStrategy,
    SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy,
    SpyOpeningRangeBreakoutMidpointStopMaxTwoStrategy,
    SpyVwapPullbackStrategy,
    SpyVwapRangeReversionOneAndHalfAtrBandStrategy,
    SpyVwapTrendContinuationActiveRvolFilterStrategy,
    SpyVwapTrendContinuationAtrDistanceFilterStrategy,
    SpyVwapTrendContinuationBasicSignalQualityFilterStrategy,
    SpyVwapTrendContinuationDailyTrendFilterStrategy,
    SpyVwapTrendContinuationLongShortBaseStrategy,
    SpyVwapTrendContinuationLooseRvolFilterStrategy,
    SpyVwapTrendContinuationNormalToActiveRvolFilterStrategy,
    SpyVwapTrendContinuationOneRTargetTimeStopStrategy,
    SpyVwapTrendContinuationOpeningDriveFilterStrategy,
    SpyVwapTrendContinuationOpeningRangeConfluenceLooseFilterStrategy,
    SpyVwapTrendContinuationOpeningRangeConfluenceStrictFilterStrategy,
    SpyVwapTrendContinuationSignalBreakEntryStrategy,
    SpyVwapTrendContinuationSignalQualityBreakEntryStrategy,
    SpyVwapTrendContinuationStrongSignalQualityFilterStrategy,
    SpyVwapTrendContinuationTimeStopStrategy,
    Strategy,
    StrategyDecisionContext,
    SymmetricSpyVwapPullbackStrategy,
    TrendDayVwapReclaimStrategy,
    get_strategy,
)


def test_orb_midpoint_strategy_enters_long_after_close_breakout() -> None:
    strategy = SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy()
    bars = (
        _bar(index=0, open=100.0, high=100.4, low=99.9, close=100.1),
        _bar(index=1, open=100.1, high=100.5, low=100.0, close=100.2),
        _bar(index=2, open=100.2, high=100.6, low=100.1, close=100.3),
        _bar(index=3, open=100.3, high=100.7, low=100.2, close=100.4),
        _bar(index=4, open=100.4, high=100.8, low=100.3, close=100.5),
        _bar(index=5, open=100.5, high=100.9, low=100.4, close=100.6),
        _bar(index=6, open=100.6, high=101.2, low=100.5, close=101.1),
    )

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == strategy.name
    assert "orb_close_breakout_long" in decisions[-1].reason


def test_orb_midpoint_strategy_exits_long_at_stop_price() -> None:
    strategy = SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy()
    setup_bars = (
        _bar(index=0, open=100.0, high=100.4, low=99.9, close=100.1),
        _bar(index=1, open=100.1, high=100.5, low=100.0, close=100.2),
        _bar(index=2, open=100.2, high=100.6, low=100.1, close=100.3),
        _bar(index=3, open=100.3, high=100.7, low=100.2, close=100.4),
        _bar(index=4, open=100.4, high=100.8, low=100.3, close=100.5),
        _bar(index=5, open=100.5, high=100.9, low=100.4, close=100.6),
        _bar(index=6, open=100.6, high=101.2, low=100.5, close=101.1),
    )
    _decisions_for_bars(strategy, setup_bars, position_quantity=Decimal("0"))

    stop_bar = _bar(index=7, open=100.9, high=101.0, low=100.2, close=100.4)
    decision = strategy.decide(
        bar=stop_bar,
        context=_context(
            bar=stop_bar,
            sequence_number=8,
            previous_bar=setup_bars[-1],
            position_quantity=Decimal("1"),
        ),
    )

    assert decision.action == DecisionAction.EXIT_LONG
    assert "orb_stop_long@" in decision.reason


def test_orb_max_two_strategy_allows_second_trade_after_first_exit() -> None:
    strategy = SpyOpeningRangeBreakoutMidpointStopMaxTwoStrategy()
    first_setup = (
        _bar(index=0, open=100.0, high=100.4, low=99.9, close=100.1),
        _bar(index=1, open=100.1, high=100.5, low=100.0, close=100.2),
        _bar(index=2, open=100.2, high=100.6, low=100.1, close=100.3),
        _bar(index=3, open=100.3, high=100.7, low=100.2, close=100.4),
        _bar(index=4, open=100.4, high=100.8, low=100.3, close=100.5),
        _bar(index=5, open=100.5, high=100.9, low=100.4, close=100.6),
        _bar(index=6, open=100.6, high=101.2, low=100.5, close=101.1),
    )
    _decisions_for_bars(strategy, first_setup, position_quantity=Decimal("0"))

    exit_bar = _bar(index=7, open=100.9, high=101.0, low=100.2, close=100.4)
    strategy.decide(
        bar=exit_bar,
        context=_context(
            bar=exit_bar,
            sequence_number=8,
            previous_bar=first_setup[-1],
            position_quantity=Decimal("1"),
        ),
    )

    second_signal = _bar(index=8, open=100.6, high=101.3, low=100.6, close=101.2)
    decision = strategy.decide(
        bar=second_signal,
        context=_context(
            bar=second_signal,
            sequence_number=9,
            previous_bar=exit_bar,
            position_quantity=Decimal("0"),
        ),
    )

    assert decision.action == DecisionAction.ENTER_LONG
    assert "orb_close_breakout_long" in decision.reason


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


def test_opening_drive_quality_vwap_reclaim_enters_when_opening_close_is_strong() -> None:
    strategy = OpeningDriveQualityVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    current_day = _trend_day_reclaim_setup_bars(day=26)
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == "trend-day-vwap-reclaim-v3-opening-drive"
    assert "trend_day_vwap_reclaim" in decisions[-1].reason


def test_opening_drive_quality_vwap_reclaim_keeps_daily_context_gate_first() -> None:
    strategy = OpeningDriveQualityVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(24)])
    current_day = _trend_day_reclaim_setup_bars(day=26)
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "daily_context_not_ready" in decisions[-1].reason


def test_opening_drive_quality_vwap_reclaim_rejects_weak_opening_close_location() -> None:
    strategy = OpeningDriveQualityVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    current_day = (
        _bar(index=0, open=100.0, high=110.0, low=100.0, close=101.0, day=26),
        _bar(index=1, open=101.0, high=110.0, low=100.0, close=102.0, day=26),
        _bar(index=2, open=102.0, high=110.0, low=100.0, close=103.0, day=26),
        _bar(index=3, open=103.0, high=110.0, low=100.0, close=104.0, day=26),
        _bar(index=4, open=104.0, high=110.0, low=100.0, close=105.0, day=26),
        _bar(index=5, open=105.0, high=110.0, low=100.0, close=105.0, day=26),
        _bar(index=6, open=108.0, high=108.0, low=104.0, close=106.0, day=26),
        _bar(index=7, open=106.0, high=112.0, low=105.0, close=112.0, day=26),
    )
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "opening_drive_close_position_too_weak" in decisions[-1].reason


def test_opening_drive_quality_vwap_reclaim_treats_flat_opening_range_as_neutral() -> None:
    strategy = OpeningDriveQualityVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    current_day = (
        _bar(index=0, open=100.0, high=100.0, low=100.0, close=100.0, day=26),
        _bar(index=1, open=100.0, high=100.0, low=100.0, close=100.0, day=26),
        _bar(index=2, open=100.0, high=100.0, low=100.0, close=100.0, day=26),
        _bar(index=3, open=100.0, high=100.0, low=100.0, close=100.0, day=26),
        _bar(index=4, open=100.0, high=100.0, low=100.0, close=100.0, day=26),
        _bar(index=5, open=100.0, high=100.0, low=100.0, close=100.0, day=26),
        _bar(index=6, open=104.0, high=104.0, low=99.0, close=103.0, day=26),
        _bar(index=7, open=103.5, high=105.2, low=100.0, close=105.0, day=26),
    )
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "opening_drive_close_position_too_weak" in decisions[-1].reason


def test_rvol_bucket_vwap_reclaim_enters_when_opening_rvol_is_normal_or_better() -> None:
    strategy = RvolBucketVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
        relative_volume_lookback_sessions=1,
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    prior_day = _trend_day_reclaim_setup_bars(day=25, volume=1_000)
    current_day = _trend_day_reclaim_setup_bars(day=26, volume=1_100)
    _decisions_for_bars(strategy, prior_day, position_quantity=Decimal("0"))
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == "trend-day-vwap-reclaim-v4-rvol-buckets"
    assert "trend_day_vwap_reclaim" in decisions[-1].reason


def test_rvol_bucket_vwap_reclaim_rejects_low_opening_rvol() -> None:
    strategy = RvolBucketVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
        relative_volume_lookback_sessions=1,
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    prior_day = _trend_day_reclaim_setup_bars(day=25, volume=2_000)
    current_day = _trend_day_reclaim_setup_bars(day=26, volume=1_000)
    _decisions_for_bars(strategy, prior_day, position_quantity=Decimal("0"))
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "opening_rvol_too_low" in decisions[-1].reason


def test_rvol_bucket_vwap_reclaim_skips_rvol_filter_until_history_exists() -> None:
    strategy = RvolBucketVwapReclaimStrategy(
        max_entry_distance_from_vwap=Decimal("0.03"),
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    current_day = _trend_day_reclaim_setup_bars(day=26)
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert "trend_day_vwap_reclaim" in decisions[-1].reason


def test_dynamic_vwap_distance_reclaim_enters_when_atr_distance_passes() -> None:
    strategy = DynamicVwapDistanceReclaimStrategy(
        atr_period_5m=2,
        max_vwap_distance_atr_multiple=Decimal("3.0"),
        relative_volume_lookback_sessions=1,
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    prior_day = _trend_day_reclaim_setup_bars(day=25, volume=1_000)
    current_day = _trend_day_reclaim_setup_bars(day=26, volume=1_100)
    _decisions_for_bars(strategy, prior_day, position_quantity=Decimal("0"))
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == "trend-day-vwap-reclaim-v5-dynamic-vwap-distance"
    assert "trend_day_vwap_reclaim" in decisions[-1].reason


def test_dynamic_vwap_distance_reclaim_rejects_entries_too_far_above_vwap() -> None:
    strategy = DynamicVwapDistanceReclaimStrategy(
        atr_period_5m=2,
        max_vwap_distance_atr_multiple=Decimal("0.01"),
        relative_volume_lookback_sessions=1,
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    prior_day = _trend_day_reclaim_setup_bars(day=25, volume=1_000)
    current_day = _trend_day_reclaim_setup_bars(day=26, volume=1_100)
    _decisions_for_bars(strategy, prior_day, position_quantity=Decimal("0"))
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "dynamic_vwap_distance_too_extended" in decisions[-1].reason


def test_dynamic_vwap_distance_reclaim_waits_for_atr_history() -> None:
    strategy = DynamicVwapDistanceReclaimStrategy(
        atr_period_5m=20,
        max_entry_distance_from_vwap=Decimal("0.03"),
    )

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    current_day = _trend_day_reclaim_setup_bars(day=26)
    decisions = _decisions_for_bars(strategy, current_day, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "dynamic_vwap_distance_atr_not_ready" in decisions[-1].reason


def test_long_short_trend_continuation_base_enters_long_on_vwap_reclaim() -> None:
    strategy = SpyVwapTrendContinuationLongShortBaseStrategy(atr_period_5m=2)

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == "spy-vwap-trend-continuation-long-short-base"
    assert "long_vwap_trend_continuation_reclaim" in decisions[-1].reason


def test_long_short_trend_continuation_base_enters_short_on_vwap_rejection() -> None:
    strategy = SpyVwapTrendContinuationLongShortBaseStrategy(atr_period_5m=2)

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_short_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_SHORT
    assert decisions[-1].strategy_name == "spy-vwap-trend-continuation-long-short-base"
    assert "short_vwap_trend_continuation_rejection" in decisions[-1].reason


def test_long_short_trend_continuation_base_exits_long_on_signal_low_failure() -> None:
    strategy = SpyVwapTrendContinuationLongShortBaseStrategy(atr_period_5m=2)
    setup_bars = _long_short_base_long_setup_bars()
    _decisions_for_bars(strategy, setup_bars, position_quantity=Decimal("0"))

    exit_bar = _bar(index=7, open=103.8, high=104.0, low=100.8, close=101.0)
    decision = strategy.decide(
        bar=exit_bar,
        context=_context(
            bar=exit_bar,
            sequence_number=8,
            previous_bar=setup_bars[-1],
            position_quantity=Decimal("1"),
        ),
    )

    assert decision.action == DecisionAction.EXIT_LONG
    assert "close_below_signal_bar_low" in decision.reason


def test_long_short_trend_continuation_base_waits_for_atr_history() -> None:
    strategy = SpyVwapTrendContinuationLongShortBaseStrategy(atr_period_5m=20)

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.HOLD
    assert "base_atr_not_ready" in decisions[-1].reason


def test_long_short_daily_trend_filter_allows_long_in_bullish_context() -> None:
    strategy = SpyVwapTrendContinuationDailyTrendFilterStrategy(atr_period_5m=2)

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(25)])
    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(day=26),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert (
        decisions[-1].strategy_name == "spy-vwap-trend-continuation-long-short-daily-trend-filter"
    )
    assert "long_vwap_trend_continuation_reclaim" in decisions[-1].reason


def test_long_short_daily_trend_filter_allows_short_in_bearish_context() -> None:
    strategy = SpyVwapTrendContinuationDailyTrendFilterStrategy(atr_period_5m=2)

    _seed_completed_daily_closes(strategy, closes=[125 - index for index in range(25)])
    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_short_setup_bars(day=26),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_SHORT
    assert "short_vwap_trend_continuation_rejection" in decisions[-1].reason


def test_long_short_daily_trend_filter_blocks_long_in_bearish_context() -> None:
    strategy = SpyVwapTrendContinuationDailyTrendFilterStrategy(atr_period_5m=2)

    _seed_completed_daily_closes(strategy, closes=[125 - index for index in range(25)])
    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(day=26),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.HOLD
    assert "short_base_entry_filter_not_met" in decisions[-1].reason


def test_long_short_daily_trend_filter_waits_for_daily_history() -> None:
    strategy = SpyVwapTrendContinuationDailyTrendFilterStrategy(atr_period_5m=2)

    _seed_completed_daily_closes(strategy, closes=[75.6 + index for index in range(24)])
    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(day=26),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.HOLD
    assert "daily_context_not_ready" in decisions[-1].reason


def test_long_short_opening_drive_filter_allows_long_after_bullish_drive() -> None:
    strategy = SpyVwapTrendContinuationOpeningDriveFilterStrategy(atr_period_5m=2)

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert (
        decisions[-1].strategy_name == "spy-vwap-trend-continuation-long-short-opening-drive-filter"
    )
    assert "long_vwap_trend_continuation_reclaim" in decisions[-1].reason


def test_long_short_opening_drive_filter_allows_short_after_bearish_drive() -> None:
    strategy = SpyVwapTrendContinuationOpeningDriveFilterStrategy(atr_period_5m=2)

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_short_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_SHORT
    assert "short_vwap_trend_continuation_rejection" in decisions[-1].reason


def test_long_short_opening_drive_filter_rejects_neutral_drive() -> None:
    strategy = SpyVwapTrendContinuationOpeningDriveFilterStrategy(atr_period_5m=2)
    neutral_opening_drive = (
        _bar(index=0, open=100.0, high=101.0, low=99.0, close=100.0),
        _bar(index=1, open=100.0, high=101.0, low=100.0, close=100.5),
        _bar(index=2, open=100.5, high=102.0, low=100.5, close=101.0),
        _bar(index=3, open=101.0, high=102.0, low=101.0, close=101.5),
        _bar(index=4, open=101.5, high=103.0, low=101.5, close=102.0),
        _bar(index=5, open=102.0, high=103.0, low=99.0, close=100.5),
        _bar(index=6, open=102.8, high=104.5, low=101.5, close=104.0),
    )

    decisions = _decisions_for_bars(
        strategy,
        neutral_opening_drive,
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.HOLD
    assert "neutral_opening_drive" in decisions[-1].reason


def test_long_short_loose_rvol_filter_allows_missing_history() -> None:
    strategy = SpyVwapTrendContinuationLooseRvolFilterStrategy(atr_period_5m=2)

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert decisions[-1].strategy_name == "spy-vwap-trend-continuation-long-short-rvol-loose-filter"


def test_long_short_active_rvol_filter_requires_active_opening_volume() -> None:
    strategy = SpyVwapTrendContinuationActiveRvolFilterStrategy(
        atr_period_5m=2,
        rvol_lookback_sessions=1,
    )

    _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(day=25, volume=2_000),
        position_quantity=Decimal("0"),
    )
    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(day=26, volume=1_000),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.HOLD
    assert "opening_rvol_too_low" in decisions[-1].reason


def test_long_short_active_rvol_filter_enters_when_rvol_is_active() -> None:
    strategy = SpyVwapTrendContinuationActiveRvolFilterStrategy(
        atr_period_5m=2,
        rvol_lookback_sessions=1,
    )

    _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(day=25, volume=1_000),
        position_quantity=Decimal("0"),
    )
    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(day=26, volume=1_500),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_LONG


def test_long_short_normal_active_rvol_filter_rejects_event_like_rvol() -> None:
    strategy = SpyVwapTrendContinuationNormalToActiveRvolFilterStrategy(
        atr_period_5m=2,
        rvol_lookback_sessions=1,
    )

    _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(day=25, volume=1_000),
        position_quantity=Decimal("0"),
    )
    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(day=26, volume=2_000),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.HOLD
    assert "opening_rvol_too_high" in decisions[-1].reason


def test_long_short_atr_distance_filter_enters_when_distance_is_allowed() -> None:
    strategy = SpyVwapTrendContinuationAtrDistanceFilterStrategy(
        atr_period_5m=2,
        max_vwap_distance_atr_multiple=Decimal("3.0"),
    )

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert (
        decisions[-1].strategy_name == "spy-vwap-trend-continuation-long-short-atr-distance-filter"
    )


def test_long_short_atr_distance_filter_rejects_extended_entries() -> None:
    strategy = SpyVwapTrendContinuationAtrDistanceFilterStrategy(
        atr_period_5m=2,
        max_vwap_distance_atr_multiple=Decimal("0.10"),
    )

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.HOLD
    assert "atr_vwap_distance_too_extended" in decisions[-1].reason


def test_long_short_vwap_opening_range_confluence_filter_enters_when_near_orh() -> None:
    strategy = SpyVwapTrendContinuationOpeningRangeConfluenceLooseFilterStrategy(atr_period_5m=2)

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert (
        decisions[-1].strategy_name
        == "spy-vwap-trend-continuation-long-short-vwap-or-confluence-1-00-filter"
    )


def test_long_short_vwap_opening_range_confluence_filter_rejects_when_too_wide() -> None:
    strategy = SpyVwapTrendContinuationOpeningRangeConfluenceStrictFilterStrategy(atr_period_5m=2)

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.HOLD
    assert "vwap_opening_range_confluence_too_wide" in decisions[-1].reason


def test_long_short_basic_signal_quality_filter_enters_on_good_signal_bar() -> None:
    strategy = SpyVwapTrendContinuationBasicSignalQualityFilterStrategy(atr_period_5m=2)

    decisions = _decisions_for_bars(
        strategy,
        _long_short_base_long_setup_bars(),
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert (
        decisions[-1].strategy_name
        == "spy-vwap-trend-continuation-long-short-signal-quality-basic-filter"
    )


def test_long_short_strong_signal_quality_filter_rejects_small_body_signal() -> None:
    strategy = SpyVwapTrendContinuationStrongSignalQualityFilterStrategy(atr_period_5m=2)
    small_body_signal = (
        *_long_short_base_long_setup_bars()[:6],
        _bar(index=6, open=103.9, high=104.5, low=101.5, close=104.0),
    )

    decisions = _decisions_for_bars(
        strategy,
        small_body_signal,
        position_quantity=Decimal("0"),
    )

    assert decisions[-1].action == DecisionAction.HOLD
    assert "signal_bar_body_too_small" in decisions[-1].reason


def test_long_short_signal_break_entry_waits_for_next_bar_confirmation() -> None:
    strategy = SpyVwapTrendContinuationSignalBreakEntryStrategy(atr_period_5m=2)
    bars = (
        *_long_short_base_long_setup_bars(),
        _bar(index=7, open=104.4, high=105.2, low=104.1, close=104.9),
    )

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-2].action == DecisionAction.HOLD
    assert "long_signal_bar_break_pending" in decisions[-2].reason
    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert "long_signal_bar_break_entry@104.5" in decisions[-1].reason


def test_long_short_signal_break_entry_expires_without_confirmation() -> None:
    strategy = SpyVwapTrendContinuationSignalBreakEntryStrategy(atr_period_5m=2)
    bars = (
        *_long_short_base_long_setup_bars(),
        _bar(index=7, open=104.0, high=104.5, low=103.5, close=104.1),
    )

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.HOLD
    assert "signal_bar_break_expired" in decisions[-1].reason


def test_long_short_signal_quality_break_entry_combines_quality_and_break() -> None:
    strategy = SpyVwapTrendContinuationSignalQualityBreakEntryStrategy(atr_period_5m=2)
    bars = (
        *_long_short_base_long_setup_bars(),
        _bar(index=7, open=104.6, high=105.2, low=104.1, close=104.9),
    )

    decisions = _decisions_for_bars(strategy, bars, position_quantity=Decimal("0"))

    assert decisions[-1].action == DecisionAction.ENTER_LONG
    assert "long_signal_bar_break_entry@104.6" in decisions[-1].reason


def test_long_short_time_stop_exits_stalled_long_at_current_close() -> None:
    strategy = SpyVwapTrendContinuationTimeStopStrategy(atr_period_5m=2, time_stop_bars=2)
    setup_bars = _long_short_base_long_setup_bars()
    _decisions_for_bars(strategy, setup_bars, position_quantity=Decimal("0"))

    first_hold_bar = _bar(index=7, open=104.2, high=104.4, low=103.8, close=104.1)
    first_decision = strategy.decide(
        bar=first_hold_bar,
        context=_context(
            bar=first_hold_bar,
            sequence_number=8,
            previous_bar=setup_bars[-1],
            position_quantity=Decimal("1"),
            average_entry_price=Decimal("104.2"),
        ),
    )
    stalled_bar = _bar(index=8, open=104.1, high=104.3, low=103.9, close=104.0)
    stalled_decision = strategy.decide(
        bar=stalled_bar,
        context=_context(
            bar=stalled_bar,
            sequence_number=9,
            previous_bar=first_hold_bar,
            position_quantity=Decimal("1"),
            average_entry_price=Decimal("104.2"),
        ),
    )

    assert first_decision.action == DecisionAction.HOLD
    assert stalled_decision.action == DecisionAction.EXIT_LONG
    assert "time_stop_stalled_exit@104.0" in stalled_decision.reason


def test_long_short_time_stop_holds_after_enough_open_r_progress() -> None:
    strategy = SpyVwapTrendContinuationTimeStopStrategy(atr_period_5m=2, time_stop_bars=2)
    setup_bars = _long_short_base_long_setup_bars()
    _decisions_for_bars(strategy, setup_bars, position_quantity=Decimal("0"))

    progress_bar = _bar(index=7, open=104.2, high=105.4, low=104.0, close=105.2)
    strategy.decide(
        bar=progress_bar,
        context=_context(
            bar=progress_bar,
            sequence_number=8,
            previous_bar=setup_bars[-1],
            position_quantity=Decimal("1"),
            average_entry_price=Decimal("104.2"),
        ),
    )
    later_bar = _bar(index=8, open=105.0, high=105.1, low=104.2, close=104.8)
    decision = strategy.decide(
        bar=later_bar,
        context=_context(
            bar=later_bar,
            sequence_number=9,
            previous_bar=progress_bar,
            position_quantity=Decimal("1"),
            average_entry_price=Decimal("104.2"),
        ),
    )

    assert decision.action == DecisionAction.HOLD
    assert "long_base_thesis_still_valid" in decision.reason


def test_long_short_r_target_time_stop_keeps_r_target_exit() -> None:
    strategy = SpyVwapTrendContinuationOneRTargetTimeStopStrategy(atr_period_5m=2)
    setup_bars = _long_short_base_long_setup_bars()
    _decisions_for_bars(strategy, setup_bars, position_quantity=Decimal("0"))

    target_bar = _bar(index=7, open=104.2, high=107.5, low=104.0, close=106.8)
    decision = strategy.decide(
        bar=target_bar,
        context=_context(
            bar=target_bar,
            sequence_number=8,
            previous_bar=setup_bars[-1],
            position_quantity=Decimal("1"),
            average_entry_price=Decimal("104.2"),
        ),
    )

    assert decision.action == DecisionAction.EXIT_LONG
    assert "r_target_exit@" in decision.reason


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


def test_active_strategy_registry_returns_close_momentum() -> None:
    strategy = get_strategy("close-momentum")

    assert strategy.name == "close-momentum"


def test_archived_vwap_family_is_not_in_active_strategy_registry() -> None:
    archived_names = (
        "spy-vwap-pullback",
        "spy-vwap-pullback-long-short",
        "trend-day-vwap-reclaim",
        "trend-day-vwap-reclaim-entry-filter",
        "gap-and-go-vwap-pullback",
        "trend-day-vwap-reclaim-v2-daily-context",
        "trend-day-vwap-reclaim-v3-opening-drive",
        "trend-day-vwap-reclaim-v4-rvol-buckets",
        "trend-day-vwap-reclaim-v5-dynamic-vwap-distance",
        "spy-vwap-trend-continuation-long-short-base",
        "spy-vwap-trend-continuation-long-short-daily-trend-filter",
        "spy-vwap-trend-continuation-long-short-opening-drive-filter",
        "spy-vwap-trend-continuation-long-short-rvol-loose-filter",
        "spy-vwap-trend-continuation-long-short-rvol-active-filter",
        "spy-vwap-trend-continuation-long-short-rvol-normal-active-filter",
        "spy-vwap-trend-continuation-long-short-atr-distance-filter",
        "spy-vwap-trend-continuation-long-short-signal-quality-basic-filter",
        "spy-vwap-trend-continuation-long-short-signal-quality-strong-filter",
        "spy-vwap-trend-continuation-long-short-vwap-or-confluence-1-00-filter",
        "spy-vwap-trend-continuation-long-short-vwap-or-confluence-0-50-filter",
        "spy-vwap-trend-continuation-long-short-vwap-or-confluence-0-25-filter",
        "spy-vwap-trend-continuation-long-short-initial-stop",
        "spy-vwap-trend-continuation-long-short-1-0r-target",
        "spy-vwap-trend-continuation-long-short-1-5r-target",
        "spy-vwap-trend-continuation-long-short-2-0r-target",
        "spy-vwap-trend-continuation-long-short-signal-break-entry",
        "spy-vwap-trend-continuation-long-short-signal-quality-break-entry",
        "spy-vwap-trend-continuation-long-short-time-stop-4-030r",
        "spy-vwap-trend-continuation-long-short-time-stop-3-030r",
        "spy-vwap-trend-continuation-long-short-time-stop-6-030r",
        "spy-vwap-trend-continuation-long-short-1-0r-target-time-stop",
        "spy-vwap-range-reversion-base",
        "spy-vwap-range-reversion-1-0atr-band",
        "spy-vwap-range-reversion-1-5atr-band",
    )

    for strategy_name in archived_names:
        with pytest.raises(ValueError, match="unknown strategy"):
            get_strategy(strategy_name)


def test_range_reversion_long_entry_sets_stop_below_entry() -> None:
    strategy = _ExposedRangeReversionStrategy()
    state, current_bar = _seed_range_reversion_candidate_state(
        strategy,
        current_close=Decimal("98.5"),
        previous_close=Decimal("98.4"),
    )

    action, reason = strategy.flat_position_decision(state=state, bar=current_bar)

    assert action == DecisionAction.ENTER_LONG
    assert reason == "range_reversion_long_turn_up"
    assert state.initial_stop is not None
    assert state.initial_stop < Decimal(str(current_bar.close))


def test_range_reversion_short_entry_sets_stop_above_entry() -> None:
    strategy = _ExposedRangeReversionStrategy()
    state, current_bar = _seed_range_reversion_candidate_state(
        strategy,
        current_close=Decimal("101.5"),
        previous_close=Decimal("101.6"),
    )

    action, reason = strategy.flat_position_decision(state=state, bar=current_bar)

    assert action == DecisionAction.ENTER_SHORT
    assert reason == "range_reversion_short_turn_down"
    assert state.initial_stop is not None
    assert state.initial_stop > Decimal(str(current_bar.close))


def test_range_reversion_long_rejects_invalid_stop_placement() -> None:
    strategy = _ExposedRangeReversionStrategy(stop_atr_multiple=Decimal("-0.1"))
    state, current_bar = _seed_range_reversion_candidate_state(
        strategy,
        current_close=Decimal("98.5"),
        previous_close=Decimal("98.4"),
    )

    action, reason = strategy.flat_position_decision(state=state, bar=current_bar)

    assert action == DecisionAction.HOLD
    assert reason == "invalid_long_stop_not_below_entry"


def test_range_reversion_short_rejects_invalid_stop_placement() -> None:
    strategy = _ExposedRangeReversionStrategy(stop_atr_multiple=Decimal("-0.1"))
    state, current_bar = _seed_range_reversion_candidate_state(
        strategy,
        current_close=Decimal("101.5"),
        previous_close=Decimal("101.6"),
    )

    action, reason = strategy.flat_position_decision(state=state, bar=current_bar)

    assert action == DecisionAction.HOLD
    assert reason == "invalid_short_stop_not_above_entry"


def test_range_reversion_long_same_bar_stop_beats_target_when_both_hit() -> None:
    strategy = _ExposedRangeReversionStrategy()
    state, _current_bar = _seed_range_reversion_candidate_state(
        strategy,
        current_close=Decimal("98.5"),
        previous_close=Decimal("98.4"),
    )
    state.initial_target = Decimal("100")
    state.initial_stop = Decimal("98")

    exit_bar = _bar(index=9, open=99.0, high=100.2, low=97.8, close=99.5, day=27)
    action, reason = strategy.open_long_decision(state=state, bar=exit_bar)

    assert action == DecisionAction.EXIT_LONG
    assert reason == "range_reversion_stop_exit@98"


def test_range_reversion_short_same_bar_stop_beats_target_when_both_hit() -> None:
    strategy = _ExposedRangeReversionStrategy()
    state, _current_bar = _seed_range_reversion_candidate_state(
        strategy,
        current_close=Decimal("101.5"),
        previous_close=Decimal("101.6"),
    )
    state.initial_target = Decimal("100")
    state.initial_stop = Decimal("102")

    exit_bar = _bar(index=9, open=101.0, high=102.2, low=99.8, close=100.5, day=27)
    action, reason = strategy.open_short_decision(state=state, bar=exit_bar)

    assert action == DecisionAction.EXIT_SHORT
    assert reason == "range_reversion_stop_exit@102"


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


def _long_short_base_long_setup_bars(*, day: int = 26, volume: int = 1_000) -> tuple[Bar, ...]:
    return (
        _bar(index=0, open=100.0, high=101.0, low=99.0, close=100.0, day=day, volume=volume),
        _bar(
            index=1,
            open=100.0,
            high=101.0,
            low=100.0,
            close=100.5,
            day=day,
            volume=volume,
        ),
        _bar(
            index=2,
            open=100.5,
            high=102.0,
            low=100.5,
            close=101.0,
            day=day,
            volume=volume,
        ),
        _bar(
            index=3,
            open=101.0,
            high=102.0,
            low=101.0,
            close=101.5,
            day=day,
            volume=volume,
        ),
        _bar(
            index=4,
            open=101.5,
            high=103.0,
            low=101.5,
            close=102.0,
            day=day,
            volume=volume,
        ),
        _bar(
            index=5,
            open=102.0,
            high=103.0,
            low=102.0,
            close=102.5,
            day=day,
            volume=volume,
        ),
        _bar(
            index=6,
            open=102.8,
            high=104.5,
            low=101.5,
            close=104.0,
            day=day,
            volume=volume,
        ),
    )


def _long_short_base_short_setup_bars(*, day: int = 26) -> tuple[Bar, ...]:
    return (
        _bar(index=0, open=100.0, high=101.0, low=99.0, close=100.0, day=day),
        _bar(index=1, open=100.0, high=100.0, low=99.0, close=99.5, day=day),
        _bar(index=2, open=99.5, high=99.5, low=98.0, close=99.0, day=day),
        _bar(index=3, open=99.0, high=99.0, low=98.0, close=98.5, day=day),
        _bar(index=4, open=98.5, high=98.5, low=97.0, close=98.0, day=day),
        _bar(index=5, open=98.0, high=98.0, low=97.0, close=97.5, day=day),
        _bar(index=6, open=97.2, high=98.5, low=95.5, close=96.0, day=day),
    )


def _seed_completed_daily_closes(
    strategy: SpyVwapPullbackStrategy,
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


class _ExposedRangeReversionStrategy(SpyVwapRangeReversionOneAndHalfAtrBandStrategy):
    def state_for_bar(self, bar: Bar) -> Any:
        return self._state_for_bar(bar)

    def flat_position_decision(self, *, state: Any, bar: Bar) -> tuple[DecisionAction, str]:
        return self._flat_position_decision(state=state, bar=bar)

    def open_long_decision(self, *, state: Any, bar: Bar) -> tuple[DecisionAction, str]:
        return self._open_long_decision(state=state, bar=bar)

    def open_short_decision(self, *, state: Any, bar: Bar) -> tuple[DecisionAction, str]:
        return self._open_short_decision(state=state, bar=bar)

    def set_prior_session_range(self, *, high: Decimal, low: Decimal) -> None:
        self._previous_session_high = high
        self._previous_session_low = low


def _seed_range_reversion_candidate_state(
    strategy: _ExposedRangeReversionStrategy,
    *,
    current_close: Decimal,
    previous_close: Decimal,
) -> tuple[Any, Bar]:
    current_bar = _bar(
        index=8,
        open=float(current_close),
        high=float(current_close + Decimal("0.2")),
        low=float(current_close - Decimal("0.2")),
        close=float(current_close),
        day=27,
    )
    state = strategy.state_for_bar(current_bar)
    strategy.set_prior_session_range(high=Decimal("110"), low=Decimal("90"))
    state.bars_seen = 8
    state.session_open = Decimal("100")
    state.current_vwap = Decimal("100")
    state.previous_vwap = Decimal("100")
    state.first_30_minute_high = Decimal("100.5")
    state.first_30_minute_low = Decimal("99.7")
    state.previous_bar = _bar(
        index=7,
        open=float(previous_close),
        high=float(previous_close + Decimal("0.1")),
        low=float(previous_close - Decimal("0.1")),
        close=float(previous_close),
        day=27,
    )
    state.true_ranges = [Decimal("1")] * strategy.atr_period_5m
    state.range_reversion_bars = (
        _bar(index=0, open=99.9, high=100.0, low=99.8, close=99.9, day=27),
        _bar(index=1, open=100.1, high=100.2, low=100.0, close=100.1, day=27),
        _bar(index=2, open=99.9, high=100.0, low=99.8, close=99.9, day=27),
        _bar(index=3, open=100.1, high=100.2, low=100.0, close=100.1, day=27),
        _bar(index=4, open=99.9, high=100.0, low=99.8, close=99.9, day=27),
        _bar(index=5, open=100.1, high=100.2, low=100.0, close=100.1, day=27),
    )
    return state, current_bar


def _context(
    *,
    bar: Bar,
    sequence_number: int,
    previous_bar: Bar | None,
    position_quantity: Decimal,
    average_entry_price: Decimal = Decimal("0"),
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
        average_entry_price=average_entry_price,
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
