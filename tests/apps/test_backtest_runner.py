from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from pytest import CaptureFixture
from trade_core import DecisionAction, StrategyDecision, StrategyDecisionId
from trade_data import Bar, HistoricalBarsRequest, Instrument, LocalMarketDataStore
from trade_data.sessions import MarketSessionConfig
from trade_research_app.backtest import (
    BacktestCostModel,
    default_cost_stress_scenarios,
    run_cost_stress_report,
    run_minimal_backtest,
    session_regime_tags,
)
from trade_research_app.cli import main
from trade_strategies import StrategyDecisionContext, get_strategy


def test_minimal_backtest_loads_cached_bars_and_writes_summary(tmp_path: Path) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)
    output_path = tmp_path / "backtests" / "summary.json"

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=output_path,
        strategy=get_strategy("close-momentum"),
        quantity=Decimal("1"),
    )

    assert summary.bars_loaded == 5
    assert summary.decisions == 5
    assert summary.approved_orders == 2
    assert summary.fills == 2
    assert summary.pending_orders == 0
    assert summary.ending_position == Decimal("0")
    assert summary.realized_pnl == Decimal("-1.0")
    assert summary.unrealized_pnl == Decimal("0")
    assert summary.total_pnl == Decimal("-1.0")
    expected_trade_bucket = {
        "average_holding_minutes": "10",
        "average_post_exit_max_favorable_pnl": "0.0",
        "closed_trades": 1,
        "expectancy": "-1.0",
        "losing_trades": 1,
        "max_post_exit_max_favorable_pnl": "0.0",
        "median_holding_minutes": "10",
        "median_post_exit_max_favorable_pnl": "0.0",
        "total_pnl": "-1.0",
        "win_rate": "0",
        "winning_trades": 0,
    }
    expected_empty_trade_bucket = {
        "average_holding_minutes": "0",
        "average_post_exit_max_favorable_pnl": "0",
        "closed_trades": 0,
        "expectancy": "0",
        "losing_trades": 0,
        "max_post_exit_max_favorable_pnl": "0",
        "median_holding_minutes": "0",
        "median_post_exit_max_favorable_pnl": "0",
        "total_pnl": "0",
        "win_rate": "0",
        "winning_trades": 0,
    }
    expected_trade_contribution = {
        "top_1": {
            "count": 1,
            "largest_label": "trade_0001",
            "largest_pnl": "-1.0",
            "selected_absolute_pnl": "1.0",
            "selected_pnl": "-1.0",
            "share_of_absolute_pnl": "1",
            "share_of_total_pnl": "1",
        },
        "top_10": {
            "count": 1,
            "largest_label": "trade_0001",
            "largest_pnl": "-1.0",
            "selected_absolute_pnl": "1.0",
            "selected_pnl": "-1.0",
            "share_of_absolute_pnl": "1",
            "share_of_total_pnl": "1",
        },
        "top_5": {
            "count": 1,
            "largest_label": "trade_0001",
            "largest_pnl": "-1.0",
            "selected_absolute_pnl": "1.0",
            "selected_pnl": "-1.0",
            "share_of_absolute_pnl": "1",
            "share_of_total_pnl": "1",
        },
    }
    expected_day_contribution = {
        key: {**value, "largest_label": "2026-06-26"}
        for key, value in expected_trade_contribution.items()
    }
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "approved_orders": 2,
        "average_holding_minutes": "10",
        "average_loss": "-1.0",
        "average_post_exit_max_favorable_pnl": "0.0",
        "average_win": "0",
        "bars_loaded": 5,
        "best_trade_pnl": "-1.0",
        "closed_trades": 1,
        "cost_per_closed_trade": "0.0",
        "chronological_split_breakdown": {
            "first_half": expected_trade_bucket,
            "second_half": expected_empty_trade_bucket,
        },
        "daily_breakdown": {"2026-06-26": expected_trade_bucket},
        "day_contribution_breakdown": expected_day_contribution,
        "decisions": 5,
        "ending_position": "0",
        "exit_reason_breakdown": {"close_below_previous_close": expected_trade_bucket},
        "expectancy_per_day": "-1.0",
        "expectancy_per_trade": "-1.0",
        "fills": 2,
        "gap_breakdown": {"unknown_gap": expected_trade_bucket},
        "holding_time_breakdown": {"00-30m": expected_trade_bucket},
        "instrument_id": "SPY.US",
        "longest_holding_minutes": 10,
        "losing_trades": 1,
        "max_drawdown": "-1.0",
        "max_drawdown_duration_trades": 1,
        "max_consecutive_losing_trades": 1,
        "max_post_exit_max_favorable_pnl": "0.0",
        "median_holding_minutes": "10",
        "median_post_exit_max_favorable_pnl": "0.0",
        "median_trade_pnl": "-1.0",
        "minimum_commission": "0",
        "macro_event_day_breakdown": {
            "event_day": expected_empty_trade_bucket,
            "ordinary_session": expected_trade_bucket,
        },
        "macro_event_type_breakdown": {"ordinary_session": expected_trade_bucket},
        "opening_range_breakdown": {"unknown_opening_range": expected_trade_bucket},
        "pending_orders": 0,
        "profit_factor": "0",
        "realized_pnl": "-1.0",
        "relative_volume_breakdown": {"unknown_relative_volume": expected_trade_bucket},
        "rolling_3_month_breakdown": {
            "2026-06-01_2026-08-30": expected_trade_bucket,
        },
        "rolling_6_month_breakdown": {
            "2026-06-01_2026-11-29": expected_trade_bucket,
        },
        "commission_per_share": "0",
        "slippage_bps": "0",
        "strategy_name": "close-momentum",
        "timeframe": "5Min",
        "total_commissions": "0",
        "total_execution_costs": "0.0",
        "total_slippage_cost": "0.0",
        "total_pnl": "-1.0",
        "trade_contribution_breakdown": expected_trade_contribution,
        "time_of_day_breakdown": {"09:30-10:00": expected_trade_bucket},
        "trend_breakdown": {"chop_or_mixed": expected_trade_bucket},
        "unrealized_pnl": "0",
        "win_rate": "0",
        "winning_trades": 0,
        "worst_trade_pnl": "-1.0",
    }


def test_backtest_cli_runs_against_local_cache(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)
    output_path = tmp_path / "summary.json"

    exit_code = main(
        [
            "backtest",
            "run",
            "--symbol",
            "SPY",
            "--strategy",
            "close-momentum",
            "--timeframe",
            "5Min",
            "--start",
            "2026-06-26",
            "--end",
            "2026-06-26",
            "--cache-dir",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "strategy=close-momentum" in output
    assert "bars_loaded=5" in output
    assert "pending_orders=0" in output
    assert "realized_pnl=-1.0" in output
    assert "total_pnl=-1.0" in output
    assert "slippage_bps=0" in output
    assert "total_commissions=0" in output
    assert "total_slippage_cost=0.0" in output
    assert "expectancy_per_trade=-1.0" in output
    assert "median_trade_pnl=-1.0" in output
    assert "closed_trades=1" in output
    assert "profit_factor=0" in output
    assert "max_consecutive_losing_trades=1" in output
    assert "average_holding_minutes=10" in output
    assert "median_holding_minutes=10" in output
    assert "longest_holding_minutes=10" in output
    assert "average_post_exit_max_favorable_pnl=0.0" in output
    assert "median_post_exit_max_favorable_pnl=0.0" in output
    assert "max_post_exit_max_favorable_pnl=0.0" in output


def test_default_cost_stress_scenarios_cover_slippage_and_commissions() -> None:
    scenarios = default_cost_stress_scenarios()

    assert [scenario.name for scenario in scenarios] == [
        "gross",
        "commission_only",
        "slippage_0_25bps",
        "slippage_0_5bps",
        "slippage_1bps",
        "slippage_2bps",
        "slippage_3bps",
        "slippage_5bps",
        "slippage_1bps_commission",
        "ibkr_ca_fixed_1bps",
        "ibkr_ca_tiered_1bps",
    ]
    assert scenarios[4].cost_model.slippage_bps == Decimal("1")
    assert scenarios[8].cost_model.commission_per_share == Decimal("0.005")
    assert scenarios[9].cost_model.minimum_commission == Decimal("1")
    assert scenarios[10].cost_model.commission_per_share == Decimal("0.0035")
    assert scenarios[10].cost_model.minimum_commission == Decimal("0.35")


def test_cost_stress_report_writes_compact_scenario_rows(tmp_path: Path) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)
    output_path = tmp_path / "cost-stress.json"

    report = run_cost_stress_report(
        request=request,
        cache_dir=tmp_path,
        output_path=output_path,
        strategy_factory=lambda: get_strategy("close-momentum"),
        quantity=Decimal("1"),
        scenarios=default_cost_stress_scenarios()[:2],
    )

    assert report.rows[0].scenario_name == "gross"
    assert report.rows[0].total_pnl == Decimal("-1.0")
    assert report.rows[0].cost_drag_from_gross == Decimal("0.0")
    assert report.rows[1].scenario_name == "commission_only"
    assert report.rows[1].total_pnl == Decimal("-1.010")
    assert report.rows[1].cost_drag_from_gross == Decimal("0.010")
    assert json.loads(output_path.read_text(encoding="utf-8"))["rows"][1] == {
        "closed_trades": 1,
        "commission_per_share": "0.005",
        "cost_drag_from_gross": "0.010",
        "expectancy_per_trade": "-1.010",
        "gross_edge_consumed": "0",
        "median_post_exit_max_favorable_pnl": "0.0",
        "minimum_commission": "0",
        "profit_factor": "0",
        "scenario_name": "commission_only",
        "slippage_bps": "0",
        "total_execution_costs": "0.010",
        "total_pnl": "-1.010",
    }


def test_backtest_cost_stress_cli_runs_against_local_cache(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)
    output_path = tmp_path / "stress.json"

    exit_code = main(
        [
            "backtest",
            "cost-stress",
            "--symbol",
            "SPY",
            "--strategy",
            "close-momentum",
            "--timeframe",
            "5Min",
            "--start",
            "2026-06-26",
            "--end",
            "2026-06-26",
            "--cache-dir",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "strategy=close-momentum" in output
    assert "scenario=gross" in output
    assert "scenario=slippage_1bps_commission" in output
    assert "cost_drag_from_gross=0.010" in output
    assert "median_post_exit_max_favorable_pnl=0.0" in output
    assert output_path.exists()


def test_minimal_backtest_applies_commission_costs(tmp_path: Path) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=None,
        strategy=get_strategy("close-momentum"),
        quantity=Decimal("1"),
        cost_model=BacktestCostModel(commission_per_share=Decimal("0.10")),
    )

    assert summary.fills == 2
    assert summary.total_commissions == Decimal("0.20")
    assert summary.total_execution_costs == Decimal("0.20")
    assert summary.cost_per_closed_trade == Decimal("0.20")
    assert summary.realized_pnl == Decimal("-1.20")
    assert summary.total_pnl == Decimal("-1.20")
    assert summary.expectancy_per_trade == Decimal("-1.20")
    assert summary.average_loss == Decimal("-1.20")
    assert summary.max_drawdown == Decimal("-1.20")


def test_minimal_backtest_applies_one_way_slippage(tmp_path: Path) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=None,
        strategy=get_strategy("close-momentum"),
        quantity=Decimal("1"),
        cost_model=BacktestCostModel(slippage_bps=Decimal("100")),
    )

    assert summary.fills == 2
    assert summary.total_slippage_cost == Decimal("2.020")
    assert summary.total_execution_costs == Decimal("2.020")
    assert summary.realized_pnl == Decimal("-3.020")
    assert summary.total_pnl == Decimal("-3.020")


def test_minimal_backtest_realizes_short_trade_pnl(tmp_path: Path) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=None,
        strategy=_ScriptedShortStrategy(),
        quantity=Decimal("1"),
    )

    assert summary.fills == 2
    assert summary.ending_position == Decimal("0")
    assert summary.realized_pnl == Decimal("1.0")
    assert summary.total_pnl == Decimal("1.0")
    assert summary.winning_trades == 1
    assert summary.profit_factor == Decimal("0")
    assert summary.exit_reason_breakdown["scripted_short_exit"]["total_pnl"] == "1.0"


def test_minimal_backtest_reports_trade_breakdowns(tmp_path: Path) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=None,
        strategy=get_strategy("close-momentum"),
        quantity=Decimal("1"),
    )

    assert summary.expectancy_per_day == Decimal("-1.0")
    assert summary.best_trade_pnl == Decimal("-1.0")
    assert summary.worst_trade_pnl == Decimal("-1.0")
    assert summary.max_drawdown_duration_trades == 1
    assert summary.max_consecutive_losing_trades == 1
    assert summary.average_holding_minutes == Decimal("10")
    assert summary.median_holding_minutes == Decimal("10")
    assert summary.longest_holding_minutes == 10
    assert summary.average_post_exit_max_favorable_pnl == Decimal("0.0")
    assert summary.median_post_exit_max_favorable_pnl == Decimal("0.0")
    assert summary.max_post_exit_max_favorable_pnl == Decimal("0.0")
    expected_trade_bucket = {
        "average_holding_minutes": "10",
        "average_post_exit_max_favorable_pnl": "0.0",
        "closed_trades": 1,
        "expectancy": "-1.0",
        "losing_trades": 1,
        "max_post_exit_max_favorable_pnl": "0.0",
        "median_holding_minutes": "10",
        "median_post_exit_max_favorable_pnl": "0.0",
        "total_pnl": "-1.0",
        "win_rate": "0",
        "winning_trades": 0,
    }
    assert summary.daily_breakdown == {"2026-06-26": expected_trade_bucket}
    assert summary.time_of_day_breakdown == {"09:30-10:00": expected_trade_bucket}
    assert summary.exit_reason_breakdown == {"close_below_previous_close": expected_trade_bucket}
    assert summary.holding_time_breakdown == {"00-30m": expected_trade_bucket}
    assert summary.gap_breakdown == {"unknown_gap": expected_trade_bucket}
    assert summary.opening_range_breakdown == {"unknown_opening_range": expected_trade_bucket}
    assert summary.trend_breakdown == {"chop_or_mixed": expected_trade_bucket}
    assert summary.relative_volume_breakdown == {"unknown_relative_volume": expected_trade_bucket}


def test_minimal_backtest_reports_robustness_concentration_and_splits(
    tmp_path: Path,
) -> None:
    request = _request()
    _save_two_trade_sample_bars(tmp_path, request)

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=None,
        strategy=_ScriptedTwoTradeStrategy(),
        quantity=Decimal("1"),
    )

    assert summary.closed_trades == 2
    assert summary.total_pnl == Decimal("2.0")
    assert summary.max_consecutive_losing_trades == 1
    assert summary.trade_contribution_breakdown["top_1"] == {
        "count": 1,
        "largest_label": "trade_0001",
        "largest_pnl": "3.0",
        "selected_absolute_pnl": "3.0",
        "selected_pnl": "3.0",
        "share_of_absolute_pnl": "0.75",
        "share_of_total_pnl": "1.5",
    }
    assert summary.day_contribution_breakdown["top_1"] == {
        "count": 1,
        "largest_label": "2026-06-26",
        "largest_pnl": "2.0",
        "selected_absolute_pnl": "2.0",
        "selected_pnl": "2.0",
        "share_of_absolute_pnl": "1",
        "share_of_total_pnl": "1",
    }
    assert summary.chronological_split_breakdown["first_half"]["total_pnl"] == "3.0"
    assert summary.chronological_split_breakdown["second_half"]["total_pnl"] == "-1.0"
    assert summary.rolling_3_month_breakdown["2026-06-01_2026-08-30"]["total_pnl"] == "2.0"
    assert summary.rolling_6_month_breakdown["2026-06-01_2026-11-29"]["total_pnl"] == "2.0"


def test_minimal_backtest_tags_macro_event_sessions(tmp_path: Path) -> None:
    request = _request_for_day(day=10)
    _save_macro_event_sample_bars(tmp_path, request)

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=None,
        strategy=get_strategy("close-momentum"),
        quantity=Decimal("1"),
    )

    assert summary.closed_trades == 1
    assert summary.macro_event_day_breakdown["event_day"]["closed_trades"] == 1
    assert summary.macro_event_day_breakdown["ordinary_session"]["closed_trades"] == 0
    assert summary.macro_event_type_breakdown["cpi"]["closed_trades"] == 1
    assert summary.macro_event_type_breakdown["cpi"]["total_pnl"] == "-1.0"


def test_session_regime_tags_bucket_gap_opening_range_trend_and_volume() -> None:
    bars = (
        *[
            _bar_at(day=26, hour=13, minute=30 + offset, open=100.0, close=100.0, volume=100)
            for offset in range(0, 30, 5)
        ],
        _bar_at(day=26, hour=14, minute=0, open=100.0, close=100.0, volume=100),
        *[
            _bar_at(day=29, hour=13, minute=30 + offset, open=101.0, close=101.0, volume=500)
            for offset in range(0, 30, 5)
        ],
        _bar_at(day=29, hour=14, minute=0, open=101.1, close=102.0, volume=1_000),
        _bar_at(day=29, hour=17, minute=0, open=102.0, close=104.0, volume=1_000),
    )

    tags = session_regime_tags(bars, timezone="America/New_York")

    assert tags["2026-06-26"].gap_bucket == "unknown_gap"
    assert tags["2026-06-29"].gap_bucket == "large_gap_up"
    assert tags["2026-06-29"].opening_range_state == "above_opening_range"
    assert tags["2026-06-29"].trend_state == "trend_up"
    assert tags["2026-06-29"].relative_volume_bucket == "high_relative_volume"


def _request() -> HistoricalBarsRequest:
    return _request_for_day(day=26)


def _request_for_day(*, day: int) -> HistoricalBarsRequest:
    return HistoricalBarsRequest(
        instrument=Instrument.us_equity("SPY"),
        timeframe="5Min",
        start_utc=datetime(2026, 6, day, 4, 0, tzinfo=UTC),
        end_utc=datetime(2026, 6, day + 1, 4, 0, tzinfo=UTC),
    )


def _save_sample_bars(cache_dir: Path, request: HistoricalBarsRequest) -> None:
    bars = (
        _bar(open=100.0, close=100.0, minute=30),
        _bar(open=100.0, close=101.0, minute=35),
        _bar(open=101.5, close=102.0, minute=40),
        _bar(open=102.0, close=101.0, minute=45),
        _bar(open=100.5, close=100.0, minute=50),
    )
    session_config = MarketSessionConfig.xnys_regular()
    regular_bars = tuple(
        bar for bar in bars if session_config.classify(bar.timestamp_utc) == "regular"
    )
    LocalMarketDataStore(cache_dir).save_normalized_bars(regular_bars, request, session_config)


def _save_two_trade_sample_bars(cache_dir: Path, request: HistoricalBarsRequest) -> None:
    bars = (
        _bar(open=100.0, close=100.0, minute=30),
        _bar(open=100.0, close=101.0, minute=35),
        _bar(open=101.0, close=102.0, minute=40),
        _bar(open=102.0, close=103.0, minute=45),
        _bar(open=104.0, close=104.0, minute=50),
        _bar(open=104.0, close=103.0, minute=55),
        _bar_at(day=26, hour=14, minute=0, open=103.0, close=102.0, volume=1_000),
        _bar_at(day=26, hour=14, minute=5, open=102.0, close=101.0, volume=1_000),
        _bar_at(day=26, hour=14, minute=10, open=102.0, close=102.0, volume=1_000),
    )
    session_config = MarketSessionConfig.xnys_regular()
    regular_bars = tuple(
        bar for bar in bars if session_config.classify(bar.timestamp_utc) == "regular"
    )
    LocalMarketDataStore(cache_dir).save_normalized_bars(regular_bars, request, session_config)


def _save_macro_event_sample_bars(cache_dir: Path, request: HistoricalBarsRequest) -> None:
    bars = (
        _bar_at(day=10, hour=13, minute=30, open=100.0, close=100.0, volume=1_000),
        _bar_at(day=10, hour=13, minute=35, open=100.0, close=101.0, volume=1_000),
        _bar_at(day=10, hour=13, minute=40, open=101.5, close=102.0, volume=1_000),
        _bar_at(day=10, hour=13, minute=45, open=102.0, close=101.0, volume=1_000),
        _bar_at(day=10, hour=13, minute=50, open=100.5, close=100.0, volume=1_000),
    )
    session_config = MarketSessionConfig.xnys_regular()
    regular_bars = tuple(
        bar for bar in bars if session_config.classify(bar.timestamp_utc) == "regular"
    )
    LocalMarketDataStore(cache_dir).save_normalized_bars(regular_bars, request, session_config)


def _bar(*, open: float, close: float, minute: int) -> Bar:
    return Bar(
        instrument_id="SPY.US",
        timeframe="5Min",
        timestamp_utc=datetime(2026, 6, 26, 13, minute, tzinfo=UTC),
        open=open,
        high=max(open, close),
        low=min(open, close),
        close=close,
        volume=1_000,
        session="regular",
    )


def _bar_at(
    *,
    day: int,
    hour: int,
    minute: int,
    open: float,
    close: float,
    volume: int,
) -> Bar:
    return Bar(
        instrument_id="SPY.US",
        timeframe="5Min",
        timestamp_utc=datetime(2026, 6, day, hour, minute, tzinfo=UTC),
        open=open,
        high=max(open, close),
        low=min(open, close),
        close=close,
        volume=volume,
        session="regular",
    )


class _ScriptedShortStrategy:
    name: ClassVar[str] = "scripted-short"

    def decide(
        self,
        *,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> StrategyDecision:
        action = DecisionAction.HOLD
        reason = "scripted_hold"
        if context.sequence_number == 2 and context.position_quantity == 0:
            action = DecisionAction.ENTER_SHORT
            reason = "scripted_short_entry"
        elif context.sequence_number == 4 and context.position_quantity < 0:
            action = DecisionAction.EXIT_SHORT
            reason = "scripted_short_exit"

        return StrategyDecision(
            strategy_run_id=context.strategy_run_id,
            strategy_name=self.name,
            action=action,
            input_refs=(context.input_ref,),
            reason=f"{reason}:{bar.instrument_id}",
            decided_at_utc=context.input_ref.observed_at_utc,
            strategy_decision_id=StrategyDecisionId(
                f"{context.strategy_run_id.value}-strategy-decision-{context.sequence_number:04d}"
            ),
        )


class _ScriptedTwoTradeStrategy:
    name: ClassVar[str] = "scripted-two-trade"

    def decide(
        self,
        *,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> StrategyDecision:
        action = DecisionAction.HOLD
        reason = "scripted_hold"
        if context.sequence_number in (2, 6) and context.position_quantity == 0:
            action = DecisionAction.ENTER_LONG
            reason = "scripted_long_entry"
        elif context.sequence_number in (4, 8) and context.position_quantity > 0:
            action = DecisionAction.EXIT_LONG
            reason = "scripted_long_exit"

        return StrategyDecision(
            strategy_run_id=context.strategy_run_id,
            strategy_name=self.name,
            action=action,
            input_refs=(context.input_ref,),
            reason=f"{reason}:{bar.instrument_id}",
            decided_at_utc=context.input_ref.observed_at_utc,
            strategy_decision_id=StrategyDecisionId(
                f"{context.strategy_run_id.value}-strategy-decision-{context.sequence_number:04d}"
            ),
        )
