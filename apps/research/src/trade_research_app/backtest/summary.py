"""Build the public-safe ``BacktestSummary`` from engine state and analytics.

The engine produces the raw tallies (counts, totals, closed-trade list,
MFE/MAE/R diagnostics already baked into each trade). This module owns the
final assembly: invoke metrics + breakdowns, derive long/short splits and
concentration ratios, and construct the immutable ``BacktestSummary``
record (and write the JSON artifact when requested).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

from trade_analytics.breakdowns import (
    _breakdown_closed_trades,
    _breakdown_decimal_metric,
    _chronological_split_breakdown,
    _closed_trade_breakdown,
    _day_contribution_breakdown,
    _exit_reason_breakdown,
    _holding_time_breakdown,
    _macro_event_day_breakdown,
    _macro_event_type_breakdown,
    _month_breakdown,
    _regime_breakdown,
    _rolling_window_breakdown,
    _side_breakdown,
    _time_of_day_breakdown,
    _trade_contribution_breakdown,
    _weekday_breakdown,
    _year_breakdown,
)
from trade_analytics.metrics import (
    ClosedTrade,
    _contribution_pct_of_total_pnl,
    _trade_metrics,
    _worst_rolling_pnl,
)
from trade_data import Bar, HistoricalBarsRequest
from trade_strategies import Strategy

from trade_research_app.backtest.cli_wiring import strategy_family_name, strategy_variant_name
from trade_research_app.backtest.records import BacktestCostModel, BacktestSummary


def build_summary(
    *,
    closed_trades: list[ClosedTrade],
    decisions: int,
    fills_count: int,
    risk_decisions_count: int,
    pending_orders: int,
    position: Decimal,
    average_entry_price: Decimal,
    realized_pnl: Decimal,
    total_commissions: Decimal,
    total_slippage_cost: Decimal,
    bars: Sequence[Bar],
    strategy: Strategy,
    cost_model: BacktestCostModel,
    request: HistoricalBarsRequest,
    output_path: Path | None,
) -> BacktestSummary:
    """Assemble the public-safe summary and optionally write its JSON artifact.

    Every keyword argument mirrors a piece of engine state; nothing here mutates
    the engine's position, PnL, or fills. Theanalytics package computes the
    derived breakdowns and metrics.
    """
    timezone = _session_timezone(request)
    unrealized_pnl = _mark_to_market_pnl_local(
        position=position,
        average_entry_price=average_entry_price,
        last_close=Decimal(str(bars[-1].close)) if bars else Decimal("0"),
    )
    trade_metrics = _trade_metrics(closed_trades)
    daily_breakdown = _closed_trade_breakdown(closed_trades, timezone=timezone)
    year_breakdown = _year_breakdown(closed_trades, timezone=timezone)
    month_breakdown = _month_breakdown(closed_trades, timezone=timezone)
    weekday_breakdown = _weekday_breakdown(closed_trades, timezone=timezone)
    time_of_day_breakdown = _time_of_day_breakdown(closed_trades, timezone=timezone)
    side_breakdown = _side_breakdown(closed_trades)
    exit_reason_breakdown = _exit_reason_breakdown(closed_trades)
    holding_time_breakdown = _holding_time_breakdown(closed_trades)
    gap_breakdown = _regime_breakdown(closed_trades, tag_name="gap_bucket")
    opening_range_breakdown = _regime_breakdown(closed_trades, tag_name="opening_range_state")
    opening_range_pct_breakdown = _regime_breakdown(
        closed_trades, tag_name="opening_range_pct_bucket"
    )
    opening_drive_return_breakdown = _regime_breakdown(
        closed_trades, tag_name="opening_drive_return_bucket"
    )
    opening_drive_close_position_breakdown = _regime_breakdown(
        closed_trades, tag_name="opening_drive_close_position_bucket"
    )
    daily_trend_breakdown = _regime_breakdown(closed_trades, tag_name="daily_trend_state")
    relative_volume_breakdown = _regime_breakdown(closed_trades, tag_name="relative_volume_bucket")
    signal_bar_close_location_breakdown = _regime_breakdown(
        closed_trades, tag_name="signal_bar_close_location_bucket"
    )
    signal_bar_body_pct_breakdown = _regime_breakdown(
        closed_trades, tag_name="signal_bar_body_pct_bucket"
    )
    macro_event_day_breakdown = _macro_event_day_breakdown(closed_trades)
    macro_event_type_breakdown = _macro_event_type_breakdown(closed_trades)
    trade_contribution_breakdown = _trade_contribution_breakdown(closed_trades)
    day_contribution_breakdown = _day_contribution_breakdown(closed_trades, timezone=timezone)
    chronological_split_breakdown = _chronological_split_breakdown(closed_trades)
    rolling_3_month_breakdown = _rolling_window_breakdown(
        closed_trades, timezone=timezone, window_days=91
    )
    rolling_6_month_breakdown = _rolling_window_breakdown(
        closed_trades, timezone=timezone, window_days=182
    )
    total_execution_costs = total_commissions + total_slippage_cost
    long_trades = _breakdown_closed_trades(side_breakdown, "long")
    short_trades = _breakdown_closed_trades(side_breakdown, "short")
    summary = BacktestSummary(
        strategy_name=strategy_family_name(strategy),
        variant_name=strategy_variant_name(strategy),
        instrument_id=request.instrument.instrument_id,
        timeframe=request.timeframe,
        trades=trade_metrics.closed_trades,
        long_trades=long_trades,
        short_trades=short_trades,
        gross_pnl=realized_pnl + unrealized_pnl + total_execution_costs,
        costed_pnl=realized_pnl + unrealized_pnl,
        bars_loaded=len(bars),
        decisions=decisions,
        approved_orders=risk_decisions_count,
        fills=fills_count,
        pending_orders=pending_orders,
        ending_position=position,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=realized_pnl + unrealized_pnl,
        slippage_bps=cost_model.slippage_bps,
        commission_per_share=cost_model.commission_per_share,
        minimum_commission=cost_model.minimum_commission,
        total_commissions=total_commissions,
        total_slippage_cost=total_slippage_cost,
        total_execution_costs=total_execution_costs,
        cost_per_closed_trade=(
            total_execution_costs / Decimal(trade_metrics.closed_trades)
            if trade_metrics.closed_trades
            else Decimal("0")
        ),
        closed_trades=trade_metrics.closed_trades,
        winning_trades=trade_metrics.winning_trades,
        losing_trades=trade_metrics.losing_trades,
        win_rate=trade_metrics.win_rate,
        expectancy_per_trade=trade_metrics.expectancy_per_trade,
        expectancy_per_day=(
            sum((trade.pnl for trade in closed_trades), Decimal("0"))
            / Decimal(len(daily_breakdown))
            if daily_breakdown
            else Decimal("0")
        ),
        median_trade_pnl=trade_metrics.median_trade_pnl,
        average_win=trade_metrics.average_win,
        average_loss=trade_metrics.average_loss,
        best_trade_pnl=trade_metrics.best_trade_pnl,
        worst_trade_pnl=trade_metrics.worst_trade_pnl,
        profit_factor=trade_metrics.profit_factor,
        max_drawdown=trade_metrics.max_drawdown,
        max_drawdown_duration_trades=trade_metrics.max_drawdown_duration_trades,
        max_consecutive_losing_trades=trade_metrics.max_consecutive_losing_trades,
        average_holding_minutes=trade_metrics.average_holding_minutes,
        median_holding_minutes=trade_metrics.median_holding_minutes,
        longest_holding_minutes=trade_metrics.longest_holding_minutes,
        average_post_exit_max_favorable_pnl=trade_metrics.average_post_exit_max_favorable_pnl,
        median_post_exit_max_favorable_pnl=trade_metrics.median_post_exit_max_favorable_pnl,
        max_post_exit_max_favorable_pnl=trade_metrics.max_post_exit_max_favorable_pnl,
        avg_mfe=trade_metrics.avg_mfe,
        median_mfe=trade_metrics.median_mfe,
        avg_mae=trade_metrics.avg_mae,
        median_mae=trade_metrics.median_mae,
        avg_final_r=trade_metrics.avg_final_r,
        median_final_r=trade_metrics.median_final_r,
        avg_max_favorable_r=trade_metrics.avg_max_favorable_r,
        median_max_favorable_r=trade_metrics.median_max_favorable_r,
        avg_max_adverse_r=trade_metrics.avg_max_adverse_r,
        median_max_adverse_r=trade_metrics.median_max_adverse_r,
        pct_reached_1r=trade_metrics.pct_reached_1r,
        pct_reached_2r=trade_metrics.pct_reached_2r,
        pct_reached_3r=trade_metrics.pct_reached_3r,
        pct_reached_1r_then_negative=trade_metrics.pct_reached_1r_then_negative,
        worst_rolling_3_month=_worst_rolling_pnl(rolling_3_month_breakdown),
        worst_rolling_6_month=_worst_rolling_pnl(rolling_6_month_breakdown),
        largest_trade_pct_of_total_pnl=_contribution_pct_of_total_pnl(
            trade_contribution_breakdown, "top_1"
        ),
        top_5_absolute_trades_pct_of_total_pnl=_contribution_pct_of_total_pnl(
            trade_contribution_breakdown, "top_5"
        ),
        long_pnl=_breakdown_decimal_metric(side_breakdown, "long", "total_pnl"),
        short_pnl=_breakdown_decimal_metric(side_breakdown, "short", "total_pnl"),
        long_pf=_breakdown_decimal_metric(side_breakdown, "long", "profit_factor"),
        short_pf=_breakdown_decimal_metric(side_breakdown, "short", "profit_factor"),
        long_expectancy=_breakdown_decimal_metric(side_breakdown, "long", "expectancy"),
        short_expectancy=_breakdown_decimal_metric(side_breakdown, "short", "expectancy"),
        daily_breakdown=daily_breakdown,
        year_breakdown=year_breakdown,
        month_breakdown=month_breakdown,
        weekday_breakdown=weekday_breakdown,
        time_of_day_breakdown=time_of_day_breakdown,
        side_breakdown=side_breakdown,
        exit_type_breakdown=exit_reason_breakdown,
        exit_reason_breakdown=exit_reason_breakdown,
        holding_time_breakdown=holding_time_breakdown,
        gap_breakdown=gap_breakdown,
        opening_range_breakdown=opening_range_breakdown,
        opening_range_pct_breakdown=opening_range_pct_breakdown,
        opening_drive_return_breakdown=opening_drive_return_breakdown,
        opening_drive_close_position_breakdown=opening_drive_close_position_breakdown,
        daily_trend_breakdown=daily_trend_breakdown,
        relative_volume_breakdown=relative_volume_breakdown,
        signal_bar_close_location_breakdown=signal_bar_close_location_breakdown,
        signal_bar_body_pct_breakdown=signal_bar_body_pct_breakdown,
        macro_event_day_breakdown=macro_event_day_breakdown,
        macro_event_type_breakdown=macro_event_type_breakdown,
        trade_contribution_breakdown=trade_contribution_breakdown,
        day_contribution_breakdown=day_contribution_breakdown,
        chronological_split_breakdown=chronological_split_breakdown,
        rolling_3_month_breakdown=rolling_3_month_breakdown,
        rolling_6_month_breakdown=rolling_6_month_breakdown,
        output_path=output_path,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary.to_json_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return summary


def _session_timezone(request: HistoricalBarsRequest) -> str:
    """Resolve the market session timezone for an historical bars request.

    Imported lazily so this module does not depend on ``trade_data.sessions``
    at import type (it is already a runtime dep of the app).
    """
    from trade_data.sessions import get_market_session_config

    return get_market_session_config(request.market).timezone


def _mark_to_market_pnl_local(
    *,
    position: Decimal,
    average_entry_price: Decimal,
    last_close: Decimal,
) -> Decimal:
    """Calculate unrealized PnL for the open position using the last close.

    Thin local wrapper around :func:`fill_model.mark_to_market_pnl` to keep
    this module's import graph pointed at ``fill_model`` rather than the
    engine importing it on the summary's behalf.
    """
    from trade_research_app.backtest.fill_model import mark_to_market_pnl

    return mark_to_market_pnl(
        position=position,
        average_entry_price=average_entry_price,
        last_close=last_close,
    )


__all__ = ["build_summary"]
