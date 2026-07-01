"""Completed-trade breakdowns: group trades into report buckets.

Every `*_breakdown` function returns a JSON-safe
``dict[str, dict[str, str|int]]`` mapping a bucket label to a per-bucket summary
row built by ``_trade_bucket_summary``. Bucket accessors are market-local
(timezone-aware) where dates or session times are involved.

The generic ``BreakdownDimension`` + ``breakdown_by`` collapse the repeated
"group trades by one accessor" pattern: ``_exit_reason_breakdown``,
``_holding_time_breakdown``, and every ``_regime_breakdown(tag_name=...)`` caller
are now thin wrappers over ``breakdown_by``. Adding a new report dimension is a
one-line dimension constant instead of a new function.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from trade_core import OrderSide

from trade_analytics.metrics import ClosedTrade, _median_decimal


@dataclass(frozen=True, slots=True)
class BreakdownDimension:
    """One report dimension: a name plus a per-trade bucket accessor.

    Parameters:
        name: Report-level label for the dimension (e.g. ``"gap_bucket"``).
        bucket: Callable returning a stable string bucket label for one trade.
    """

    name: str
    bucket: Callable[[ClosedTrade], str]


def breakdown_by(
    closed_trades: list[ClosedTrade],
    dimension: BreakdownDimension,
) -> dict[str, dict[str, str | int]]:
    """Group completed trades into buckets using one ``BreakdownDimension``.

    This is the generic engine behind ``_exit_reason_breakdown``,
    ``_holding_time_breakdown``, and every ``_regime_breakdown(tag_name=...)``
    caller. New report dimensions are one-line ``BreakdownDimension`` constants
    passed here, instead of copy-pasted functions.
    """
    buckets: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        buckets.setdefault(dimension.bucket(trade), []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _closed_trade_breakdown(
    closed_trades: list[ClosedTrade],
    *,
    timezone: str,
) -> dict[str, dict[str, str | int]]:
    """Group completed trades by market-local exit date."""
    zone = ZoneInfo(timezone)
    buckets: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        local_date = trade.exited_at_utc.astimezone(zone).date().isoformat()
        buckets.setdefault(local_date, []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _year_breakdown(
    closed_trades: list[ClosedTrade],
    *,
    timezone: str,
) -> dict[str, dict[str, str | int]]:
    """Group completed trades by market-local exit year."""
    zone = ZoneInfo(timezone)
    buckets: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        label = f"{trade.exited_at_utc.astimezone(zone):%Y}"
        buckets.setdefault(label, []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _month_breakdown(
    closed_trades: list[ClosedTrade],
    *,
    timezone: str,
) -> dict[str, dict[str, str | int]]:
    """Group completed trades by market-local exit month."""
    zone = ZoneInfo(timezone)
    buckets: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        label = f"{trade.exited_at_utc.astimezone(zone):%Y-%m}"
        buckets.setdefault(label, []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _time_of_day_breakdown(
    closed_trades: list[ClosedTrade],
    *,
    timezone: str,
) -> dict[str, dict[str, str | int]]:
    """Group completed trades into 30-minute market-local entry buckets."""
    zone = ZoneInfo(timezone)
    buckets: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        local_entry = trade.entered_at_utc.astimezone(zone)
        bucket_minute = 30 if local_entry.minute >= 30 else 0
        bucket_start = local_entry.replace(
            minute=bucket_minute,
            second=0,
            microsecond=0,
        )
        bucket_end = bucket_start + timedelta(minutes=30)
        label = f"{bucket_start:%H:%M}-{bucket_end:%H:%M}"
        buckets.setdefault(label, []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _side_breakdown(closed_trades: list[ClosedTrade]) -> dict[str, dict[str, str | int]]:
    """Split completed trades by the direction opened by the strategy."""
    buckets: dict[str, list[ClosedTrade]] = {
        "long": [],
        "short": [],
    }
    for trade in closed_trades:
        bucket = "long" if trade.entry_side == OrderSide.BUY else "short"
        buckets[bucket].append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _weekday_breakdown(
    closed_trades: list[ClosedTrade],
    *,
    timezone: str,
) -> dict[str, dict[str, str | int]]:
    """Group completed trades by market-local exit weekday."""
    zone = ZoneInfo(timezone)
    buckets: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        local_exit = trade.exited_at_utc.astimezone(zone)
        buckets.setdefault(f"{local_exit.weekday()}_{local_exit:%A}", []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _exit_reason_breakdown(closed_trades: list[ClosedTrade]) -> dict[str, dict[str, str | int]]:
    """Group completed trades by the strategy rule that requested the exit."""
    return breakdown_by(closed_trades, _EXIT_REASON_DIMENSION)


def _holding_time_breakdown(closed_trades: list[ClosedTrade]) -> dict[str, dict[str, str | int]]:
    """Group completed trades by elapsed time between entry and exit fills."""
    return breakdown_by(closed_trades, _HOLDING_TIME_DIMENSION)


def _regime_breakdown(
    closed_trades: list[ClosedTrade],
    *,
    tag_name: str,
) -> dict[str, dict[str, str | int]]:
    """Group completed trades by one reporting-only regime tag.

    Thin wrapper over :func:`breakdown_by` that constructs the dimension at call
    time so callers pass ``tag_name`` as a string (keeping the original call
    sites in ``summary.py`` unchanged).
    """
    return breakdown_by(
        closed_trades,
        BreakdownDimension(name=tag_name, bucket=lambda t: str(getattr(t, tag_name))),
    )


# Pre-built dimensions for the simple "group by one accessor" breakdowns.
_EXIT_REASON_DIMENSION = BreakdownDimension(
    name="exit_reason",
    bucket=lambda t: t.exit_reason,
)
_HOLDING_TIME_DIMENSION = BreakdownDimension(
    name="holding_time",
    bucket=lambda t: _holding_time_bucket(t.holding_minutes),
)


def _macro_event_day_breakdown(
    closed_trades: list[ClosedTrade],
) -> dict[str, dict[str, str | int]]:
    """Split completed trades by whether the exit session had a macro event."""
    buckets: dict[str, list[ClosedTrade]] = {
        "event_day": [],
        "ordinary_session": [],
    }
    for trade in closed_trades:
        bucket = "event_day" if trade.macro_event_labels else "ordinary_session"
        buckets[bucket].append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _macro_event_type_breakdown(
    closed_trades: list[ClosedTrade],
) -> dict[str, dict[str, str | int]]:
    """Group completed trades by scheduled macro event type.

    A trade can appear in more than one event-type bucket when two releases fall
    on the same session, so use `macro_event_day_breakdown` for mutually
    exclusive event-day versus ordinary-session totals.
    """
    buckets: dict[str, list[ClosedTrade]] = {"ordinary_session": []}
    for trade in closed_trades:
        if not trade.macro_event_labels:
            buckets["ordinary_session"].append(trade)
            continue
        for label in trade.macro_event_labels:
            buckets.setdefault(label, []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _trade_contribution_breakdown(
    closed_trades: list[ClosedTrade],
) -> dict[str, dict[str, str | int]]:
    """Report whether total PnL is concentrated in a few completed trades."""
    return _contribution_breakdown(
        [(f"trade_{index:04d}", trade.pnl) for index, trade in enumerate(closed_trades, start=1)]
    )


def _day_contribution_breakdown(
    closed_trades: list[ClosedTrade],
    *,
    timezone: str,
) -> dict[str, dict[str, str | int]]:
    """Report whether total PnL is concentrated in a few market-local days."""
    zone = ZoneInfo(timezone)
    day_pnls: dict[str, Decimal] = {}
    for trade in closed_trades:
        local_date = trade.exited_at_utc.astimezone(zone).date().isoformat()
        day_pnls[local_date] = day_pnls.get(local_date, Decimal("0")) + trade.pnl
    return _contribution_breakdown(sorted(day_pnls.items()))


def _contribution_breakdown(
    labeled_pnls: Sequence[tuple[str, Decimal]],
) -> dict[str, dict[str, str | int]]:
    """Summarize top-N absolute PnL contribution for trades or sessions."""
    total_pnl = sum((pnl for _, pnl in labeled_pnls), Decimal("0"))
    total_absolute_pnl = sum((abs(pnl) for _, pnl in labeled_pnls), Decimal("0"))
    ranked = sorted(labeled_pnls, key=lambda item: abs(item[1]), reverse=True)
    return {
        f"top_{top_n}": _contribution_bucket(
            ranked[:top_n],
            total_pnl=total_pnl,
            total_absolute_pnl=total_absolute_pnl,
        )
        for top_n in (1, 5, 10)
    }


def _contribution_bucket(
    selected: Sequence[tuple[str, Decimal]],
    *,
    total_pnl: Decimal,
    total_absolute_pnl: Decimal,
) -> dict[str, str | int]:
    """Build one top-N concentration row using JSON-safe primitives."""
    selected_pnl = sum((pnl for _, pnl in selected), Decimal("0"))
    selected_absolute_pnl = sum((abs(pnl) for _, pnl in selected), Decimal("0"))
    largest_label, largest_pnl = selected[0] if selected else ("", Decimal("0"))
    return {
        "count": len(selected),
        "selected_pnl": str(selected_pnl),
        "selected_absolute_pnl": str(selected_absolute_pnl),
        "share_of_total_pnl": str(selected_pnl / total_pnl if total_pnl else Decimal("0")),
        "share_of_absolute_pnl": str(
            selected_absolute_pnl / total_absolute_pnl if total_absolute_pnl else Decimal("0")
        ),
        "largest_label": largest_label,
        "largest_pnl": str(largest_pnl),
    }


def _chronological_split_breakdown(
    closed_trades: list[ClosedTrade],
) -> dict[str, dict[str, str | int]]:
    """Split completed trades into first and second chronological halves."""
    midpoint = (len(closed_trades) + 1) // 2
    return {
        "first_half": _trade_bucket_summary(closed_trades[:midpoint]),
        "second_half": _trade_bucket_summary(closed_trades[midpoint:]),
    }


def _rolling_window_breakdown(
    closed_trades: list[ClosedTrade],
    *,
    timezone: str,
    window_days: int,
) -> dict[str, dict[str, str | int]]:
    """Summarize month-stepped rolling windows by market-local exit date."""
    if not closed_trades:
        return {}

    zone = ZoneInfo(timezone)
    trades_by_date = [
        (trade.exited_at_utc.astimezone(zone).date(), trade) for trade in closed_trades
    ]
    first_date = min(local_date for local_date, _ in trades_by_date)
    last_date = max(local_date for local_date, _ in trades_by_date)
    window_start = first_date.replace(day=1)
    windows: dict[str, dict[str, str | int]] = {}

    while window_start <= last_date:
        window_end = window_start + timedelta(days=window_days)
        trades_in_window = [
            trade for local_date, trade in trades_by_date if window_start <= local_date < window_end
        ]
        label = f"{window_start.isoformat()}_{(window_end - timedelta(days=1)).isoformat()}"
        windows[label] = _trade_bucket_summary(trades_in_window)
        window_start = _add_month(window_start)

    return windows


def _add_month(value: date) -> date:
    """Return the first day of the next calendar month."""
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _holding_time_bucket(holding_minutes: int) -> str:
    """Return a stable human-readable holding-time bucket label."""
    if holding_minutes < 30:
        return "00-30m"
    if holding_minutes < 60:
        return "30-60m"
    if holding_minutes < 120:
        return "60-120m"
    return "120m+"


def _trade_bucket_summary(trades: list[ClosedTrade]) -> dict[str, str | int]:
    """Summarize one bucket of completed trades."""
    pnls = [trade.pnl for trade in trades]
    holding_minutes = [Decimal(trade.holding_minutes) for trade in trades]
    post_exit_max_favorable_pnls = [trade.post_exit_max_favorable_pnl for trade in trades]
    total_pnl = sum(pnls, Decimal("0"))
    winning_pnls = [pnl for pnl in pnls if pnl > 0]
    losing_pnls = [pnl for pnl in pnls if pnl < 0]
    winning_trades = sum(1 for pnl in pnls if pnl > 0)
    losing_trades = sum(1 for pnl in pnls if pnl < 0)
    gross_profit = sum(winning_pnls, Decimal("0"))
    gross_loss = abs(sum(losing_pnls, Decimal("0")))
    return {
        "closed_trades": len(trades),
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": str(Decimal(winning_trades) / Decimal(len(pnls)) if pnls else Decimal("0")),
        "total_pnl": str(total_pnl),
        "expectancy": str(total_pnl / Decimal(len(pnls)) if pnls else Decimal("0")),
        "average_win": str(
            gross_profit / Decimal(len(winning_pnls)) if winning_pnls else Decimal("0")
        ),
        "average_loss": str(
            sum(losing_pnls, Decimal("0")) / Decimal(len(losing_pnls))
            if losing_pnls
            else Decimal("0")
        ),
        "profit_factor": str(
            gross_profit / gross_loss if gross_profit > 0 and gross_loss > 0 else Decimal("0")
        ),
        "average_holding_minutes": str(
            sum(holding_minutes, Decimal("0")) / Decimal(len(holding_minutes))
            if holding_minutes
            else Decimal("0")
        ),
        "median_holding_minutes": str(_median_decimal(holding_minutes)),
        "average_post_exit_max_favorable_pnl": str(
            sum(post_exit_max_favorable_pnls, Decimal("0"))
            / Decimal(len(post_exit_max_favorable_pnls))
            if post_exit_max_favorable_pnls
            else Decimal("0")
        ),
        "median_post_exit_max_favorable_pnl": str(_median_decimal(post_exit_max_favorable_pnls)),
        "max_post_exit_max_favorable_pnl": str(
            max(post_exit_max_favorable_pnls) if post_exit_max_favorable_pnls else Decimal("0")
        ),
        "avg_mfe": str(
            sum((t.mfe for t in trades), Decimal("0")) / Decimal(len(trades))
            if trades
            else Decimal("0")
        ),
        "median_mfe": str(_median_decimal([t.mfe for t in trades])),
        "avg_mae": str(
            sum((t.mae for t in trades), Decimal("0")) / Decimal(len(trades))
            if trades
            else Decimal("0")
        ),
        "median_mae": str(_median_decimal([t.mae for t in trades])),
        "avg_final_r": str(
            sum((t.final_r for t in trades), Decimal("0")) / Decimal(len(trades))
            if trades
            else Decimal("0")
        ),
        "avg_max_favorable_r": str(
            sum((t.max_favorable_r for t in trades), Decimal("0")) / Decimal(len(trades))
            if trades
            else Decimal("0")
        ),
        "avg_max_adverse_r": str(
            sum((t.max_adverse_r for t in trades), Decimal("0")) / Decimal(len(trades))
            if trades
            else Decimal("0")
        ),
        "pct_reached_1r": str(
            Decimal(sum(1 for t in trades if t.reached_1r)) / Decimal(len(trades))
            if trades
            else Decimal("0")
        ),
        "pct_reached_2r": str(
            Decimal(sum(1 for t in trades if t.reached_2r)) / Decimal(len(trades))
            if trades
            else Decimal("0")
        ),
        "pct_reached_3r": str(
            Decimal(sum(1 for t in trades if t.reached_3r)) / Decimal(len(trades))
            if trades
            else Decimal("0")
        ),
        "pct_reached_1r_then_negative": str(
            Decimal(sum(1 for t in trades if t.reached_1r_then_negative)) / Decimal(len(trades))
            if trades
            else Decimal("0")
        ),
    }


def _breakdown_closed_trades(
    breakdown: dict[str, dict[str, str | int]],
    bucket_name: str,
) -> int:
    """Return the closed-trade count for one named bucket."""
    bucket = breakdown.get(bucket_name, {})
    value = bucket.get("closed_trades", 0)
    return int(value) if isinstance(value, int) else 0


def _breakdown_decimal_metric(
    breakdown: dict[str, dict[str, str | int]],
    bucket_name: str,
    metric_name: str,
) -> Decimal:
    """Return one Decimal metric from a named breakdown bucket."""
    bucket = breakdown.get(bucket_name, {})
    value = bucket.get(metric_name, "0")
    return Decimal(str(value))


__all__ = [
    "BreakdownDimension",
    "_closed_trade_breakdown",
    "_year_breakdown",
    "_month_breakdown",
    "_time_of_day_breakdown",
    "_side_breakdown",
    "_weekday_breakdown",
    "_exit_reason_breakdown",
    "_holding_time_breakdown",
    "_regime_breakdown",
    "_macro_event_day_breakdown",
    "_macro_event_type_breakdown",
    "_trade_contribution_breakdown",
    "_day_contribution_breakdown",
    "_contribution_breakdown",
    "_contribution_bucket",
    "_chronological_split_breakdown",
    "_rolling_window_breakdown",
    "_add_month",
    "_holding_time_bucket",
    "_trade_bucket_summary",
    "_breakdown_closed_trades",
    "_breakdown_decimal_metric",
    "breakdown_by",
]
