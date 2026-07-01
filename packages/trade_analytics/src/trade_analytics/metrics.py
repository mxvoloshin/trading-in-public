"""Completed-trade metrics: PnL distribution, drawdown, R-multiples, MFE/MAE.

This module owns the `ClosedTrade` record and the pure aggregations that
summarize a list of completed trades. It depends only on `trade_core`
(for `OrderSide`) so it can be reused by backtest, paper/live-sim reports,
and reconciliation summaries without importing any app code.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TypedDict

from trade_core import OrderSide


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """Completed simulated trade used for diagnostics and regime summaries.

    Parameters:
        entered_at_utc: UTC timestamp of the opening fill.
        exited_at_utc: UTC timestamp of the closing fill.
        exit_reason: Strategy decision reason that requested the closing fill.
        exit_price: Simulated closing fill price after slippage.
        quantity: Simulated closed quantity.
        entry_side: Opening side for the trade. Buy means long, sell means short.
        post_exit_max_favorable_pnl: Best same-session move after exit in the
            trade's original direction, measured from the simulated exit fill price.
        gap_bucket: Session gap bucket derived from prior regular-session close.
        opening_range_state: Session state after the first 30 minutes.
        opening_range_pct_bucket: Opening-range width bucket as a share of the
            9:30 bar open.
        opening_drive_return_bucket: First-30-minute return bucket.
        opening_drive_close_position_bucket: First-30-minute close location bucket.
        daily_trend_state: Completed-daily SMA context known before session open.
        relative_volume_bucket: Opening-window volume versus trailing-session baseline.
        signal_bar_close_location_bucket: Signal-bar close location bucket.
        signal_bar_body_pct_bucket: Signal-bar body size versus range bucket.
        variant_name: Strategy variant label used for grouped research output.
        macro_event_labels: Reporting-only scheduled macro event labels for the
            market-local exit date.
        pnl: Net realized PnL after entry/exit commissions and slippage.
        entry_price: Simulated entry fill price after slippage.
        initial_stop_price: Stop price set at entry time, used as the R denominator.
        mfe: Maximum Favorable Excursion in dollars for one unit. Best price move
            in the trade's favor while the position was open.
        mae: Maximum Adverse Excursion in dollars for one unit. Worst price move
            against the trade while the position was open.
        final_r: Final PnL expressed in R multiples, where R = |entry - stop|.
        max_favorable_r: MFE expressed in R multiples.
        max_adverse_r: MAE expressed in R multiples (positive = adverse).
        reached_1r: Whether price reached +1R favorable while position was open.
        reached_2r: Whether price reached +2R favorable while position was open.
        reached_3r: Whether price reached +3R favorable while position was open.
        reached_1r_then_negative: Whether the trade reached +1R but closed negative.
    """

    entered_at_utc: datetime
    exited_at_utc: datetime
    exit_reason: str
    exit_price: Decimal
    quantity: Decimal
    entry_side: OrderSide
    post_exit_max_favorable_pnl: Decimal
    gap_bucket: str
    opening_range_state: str
    opening_range_pct_bucket: str
    opening_drive_return_bucket: str
    opening_drive_close_position_bucket: str
    daily_trend_state: str
    relative_volume_bucket: str
    signal_bar_close_location_bucket: str
    signal_bar_body_pct_bucket: str
    variant_name: str
    macro_event_labels: tuple[str, ...]
    pnl: Decimal
    entry_price: Decimal = Decimal("0")
    initial_stop_price: Decimal = Decimal("0")
    mfe: Decimal = Decimal("0")
    mae: Decimal = Decimal("0")
    final_r: Decimal = Decimal("0")
    max_favorable_r: Decimal = Decimal("0")
    max_adverse_r: Decimal = Decimal("0")
    reached_1r: bool = False
    reached_2r: bool = False
    reached_3r: bool = False
    reached_1r_then_negative: bool = False

    @property
    def holding_minutes(self) -> int:
        """Return completed holding time in whole minutes."""
        return int((self.exited_at_utc - self.entered_at_utc).total_seconds() // 60)


class _TradeDiagnostics(TypedDict):
    """Typed payload for per-trade excursion and R-multiple diagnostics."""

    entry_price: Decimal
    initial_stop_price: Decimal
    mfe: Decimal
    mae: Decimal
    final_r: Decimal
    max_favorable_r: Decimal
    max_adverse_r: Decimal
    reached_1r: bool
    reached_2r: bool
    reached_3r: bool
    reached_1r_then_negative: bool


def _compute_mfe_mae_r_diagnostics(
    *,
    entry_price: Decimal,
    initial_stop_price: Decimal,
    mfe: Decimal,
    mae: Decimal,
    pnl: Decimal,
    entry_side: OrderSide,
) -> _TradeDiagnostics:
    """Compute R-multiple diagnostics from MFE, MAE, and trade outcome.

    R is the initial risk per unit: |entry_price - initial_stop_price|.
    Favorable R is MFE / R. Adverse R is MAE / R.
    """
    risk = abs(entry_price - initial_stop_price)
    if risk == 0:
        # Degenerate case: no risk distance. Avoid division by zero.
        return {
            "entry_price": entry_price,
            "initial_stop_price": initial_stop_price,
            "mfe": mfe,
            "mae": mae,
            "final_r": Decimal("0"),
            "max_favorable_r": Decimal("0"),
            "max_adverse_r": Decimal("0"),
            "reached_1r": False,
            "reached_2r": False,
            "reached_3r": False,
            "reached_1r_then_negative": False,
        }
    final_r = pnl / risk
    max_favorable_r = mfe / risk
    max_adverse_r = mae / risk
    return {
        "entry_price": entry_price,
        "initial_stop_price": initial_stop_price,
        "mfe": mfe,
        "mae": mae,
        "final_r": final_r,
        "max_favorable_r": max_favorable_r,
        "max_adverse_r": max_adverse_r,
        "reached_1r": max_favorable_r >= Decimal("1"),
        "reached_2r": max_favorable_r >= Decimal("2"),
        "reached_3r": max_favorable_r >= Decimal("3"),
        "reached_1r_then_negative": max_favorable_r >= Decimal("1") and pnl < 0,
    }


@dataclass(frozen=True, slots=True)
class _TradeMetrics:
    """Completed-trade quality metrics for the public-safe summary."""

    closed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    expectancy_per_trade: Decimal
    median_trade_pnl: Decimal
    average_win: Decimal
    average_loss: Decimal
    best_trade_pnl: Decimal
    worst_trade_pnl: Decimal
    profit_factor: Decimal
    max_drawdown: Decimal
    max_drawdown_duration_trades: int
    max_consecutive_losing_trades: int
    average_holding_minutes: Decimal
    median_holding_minutes: Decimal
    longest_holding_minutes: int
    average_post_exit_max_favorable_pnl: Decimal
    median_post_exit_max_favorable_pnl: Decimal
    max_post_exit_max_favorable_pnl: Decimal
    avg_mfe: Decimal
    median_mfe: Decimal
    avg_mae: Decimal
    median_mae: Decimal
    avg_final_r: Decimal
    median_final_r: Decimal
    avg_max_favorable_r: Decimal
    median_max_favorable_r: Decimal
    avg_max_adverse_r: Decimal
    median_max_adverse_r: Decimal
    pct_reached_1r: Decimal
    pct_reached_2r: Decimal
    pct_reached_3r: Decimal
    pct_reached_1r_then_negative: Decimal


def _trade_metrics(closed_trades: list[ClosedTrade]) -> _TradeMetrics:
    """Calculate simple distribution metrics from completed trade PnL values."""
    closed_trade_pnls = [trade.pnl for trade in closed_trades]
    holding_minutes = [Decimal(trade.holding_minutes) for trade in closed_trades]
    post_exit_max_favorable_pnls = [trade.post_exit_max_favorable_pnl for trade in closed_trades]
    mfe_values = [trade.mfe for trade in closed_trades]
    mae_values = [trade.mae for trade in closed_trades]
    final_r_values = [trade.final_r for trade in closed_trades]
    max_favorable_r_values = [trade.max_favorable_r for trade in closed_trades]
    max_adverse_r_values = [trade.max_adverse_r for trade in closed_trades]
    reached_1r_count = sum(1 for trade in closed_trades if trade.reached_1r)
    reached_2r_count = sum(1 for trade in closed_trades if trade.reached_2r)
    reached_3r_count = sum(1 for trade in closed_trades if trade.reached_3r)
    reached_1r_then_negative_count = sum(
        1 for trade in closed_trades if trade.reached_1r_then_negative
    )
    winning_pnls = [pnl for pnl in closed_trade_pnls if pnl > 0]
    losing_pnls = [pnl for pnl in closed_trade_pnls if pnl < 0]
    gross_profit = sum(winning_pnls, Decimal("0"))
    gross_loss = abs(sum(losing_pnls, Decimal("0")))
    closed_trade_count = len(closed_trade_pnls)

    return _TradeMetrics(
        closed_trades=closed_trade_count,
        winning_trades=len(winning_pnls),
        losing_trades=len(losing_pnls),
        win_rate=(
            Decimal(len(winning_pnls)) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        expectancy_per_trade=(
            sum(closed_trade_pnls, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_trade_pnl=_median_decimal(closed_trade_pnls),
        average_win=(gross_profit / Decimal(len(winning_pnls)) if winning_pnls else Decimal("0")),
        average_loss=(
            sum(losing_pnls, Decimal("0")) / Decimal(len(losing_pnls))
            if losing_pnls
            else Decimal("0")
        ),
        best_trade_pnl=max(closed_trade_pnls) if closed_trade_pnls else Decimal("0"),
        worst_trade_pnl=min(closed_trade_pnls) if closed_trade_pnls else Decimal("0"),
        profit_factor=(
            gross_profit / gross_loss if gross_profit > 0 and gross_loss > 0 else Decimal("0")
        ),
        max_drawdown=_max_drawdown(closed_trade_pnls),
        max_drawdown_duration_trades=_max_drawdown_duration_trades(closed_trade_pnls),
        max_consecutive_losing_trades=_max_consecutive_losing_trades(closed_trade_pnls),
        average_holding_minutes=(
            sum(holding_minutes, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_holding_minutes=_median_decimal(holding_minutes),
        longest_holding_minutes=(
            max(trade.holding_minutes for trade in closed_trades) if closed_trades else 0
        ),
        average_post_exit_max_favorable_pnl=(
            sum(post_exit_max_favorable_pnls, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_post_exit_max_favorable_pnl=_median_decimal(post_exit_max_favorable_pnls),
        max_post_exit_max_favorable_pnl=(
            max(post_exit_max_favorable_pnls) if post_exit_max_favorable_pnls else Decimal("0")
        ),
        avg_mfe=(
            sum(mfe_values, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_mfe=_median_decimal(mfe_values),
        avg_mae=(
            sum(mae_values, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_mae=_median_decimal(mae_values),
        avg_final_r=(
            sum(final_r_values, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_final_r=_median_decimal(final_r_values),
        avg_max_favorable_r=(
            sum(max_favorable_r_values, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_max_favorable_r=_median_decimal(max_favorable_r_values),
        avg_max_adverse_r=(
            sum(max_adverse_r_values, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_max_adverse_r=_median_decimal(max_adverse_r_values),
        pct_reached_1r=(
            Decimal(reached_1r_count) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        pct_reached_2r=(
            Decimal(reached_2r_count) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        pct_reached_3r=(
            Decimal(reached_3r_count) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        pct_reached_1r_then_negative=(
            Decimal(reached_1r_then_negative_count) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
    )


def _median_decimal(values: list[Decimal]) -> Decimal:
    """Return the median value while preserving Decimal precision."""
    if not values:
        return Decimal("0")
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / Decimal("2")


def _max_drawdown(closed_trade_pnls: list[Decimal]) -> Decimal:
    """Calculate max realized drawdown from the closed-trade equity curve."""
    equity = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for trade_pnl in closed_trade_pnls:
        equity += trade_pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    return max_drawdown


def _max_drawdown_duration_trades(closed_trade_pnls: list[Decimal]) -> int:
    """Return the longest completed-trade count spent below an equity peak."""
    equity = Decimal("0")
    peak = Decimal("0")
    current_duration = 0
    max_duration = 0
    for trade_pnl in closed_trade_pnls:
        equity += trade_pnl
        if equity >= peak:
            peak = equity
            current_duration = 0
            continue
        current_duration += 1
        max_duration = max(max_duration, current_duration)
    return max_duration


def _max_consecutive_losing_trades(closed_trade_pnls: list[Decimal]) -> int:
    """Return the longest streak of closed trades with negative PnL."""
    current_streak = 0
    max_streak = 0
    for trade_pnl in closed_trade_pnls:
        if trade_pnl < 0:
            current_streak += 1
            max_streak = max(max_streak, current_streak)
            continue
        current_streak = 0
    return max_streak


def _worst_rolling_pnl(breakdown: dict[str, dict[str, str | int]]) -> Decimal:
    """Return the lowest rolling-window total PnL from a breakdown map."""
    if not breakdown:
        return Decimal("0")
    return min(Decimal(str(values["total_pnl"])) for values in breakdown.values())


def _contribution_pct_of_total_pnl(
    contribution_breakdown: dict[str, dict[str, str | int]],
    bucket_name: str,
) -> Decimal:
    """Return positive concentration share using absolute PnL versus total PnL."""
    bucket = contribution_breakdown.get(bucket_name, {})
    selected_absolute_pnl = Decimal(str(bucket.get("selected_absolute_pnl", "0")))
    selected_pnl = Decimal(str(bucket.get("selected_pnl", "0")))
    share_of_total_pnl = Decimal(str(bucket.get("share_of_total_pnl", "0")))
    if selected_pnl == 0 or share_of_total_pnl == 0:
        return Decimal("0")
    total_pnl = selected_pnl / share_of_total_pnl
    if total_pnl == 0:
        return Decimal("0")
    return selected_absolute_pnl / abs(total_pnl)


__all__ = [
    "ClosedTrade",
    "_TradeDiagnostics",
    "_compute_mfe_mae_r_diagnostics",
    "_TradeMetrics",
    "_trade_metrics",
    "_median_decimal",
    "_max_drawdown",
    "_max_drawdown_duration_trades",
    "_max_consecutive_losing_trades",
    "_worst_rolling_pnl",
    "_contribution_pct_of_total_pnl",
]
