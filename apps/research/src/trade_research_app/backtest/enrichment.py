"""Post-trade enrichment: attach research-only tags after fills are complete.

Every function here takes a list of ``ClosedTrade`` and returns a new list with
additional reporting fields populated. Tags are applied *after* execution so
they explain the backtest without becoming implicit strategy inputs.

``enrich_closed_trades`` is the public pipeline the engine calls; the
individual ``_with_*`` steps are exposed for tests that build trades directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from decimal import Decimal
from zoneinfo import ZoneInfo

from trade_analytics.metrics import ClosedTrade
from trade_analytics.session_regimes import _with_regime_tags, _with_signal_bar_quality_tags
from trade_core import OrderSide
from trade_data import Bar

from trade_research_app.macro_events import default_macro_event_calendar


def with_post_exit_max_favorable_pnl(
    closed_trades: list[ClosedTrade],
    *,
    bars: Sequence[Bar],
    timezone: str,
) -> list[ClosedTrade]:
    """Attach the best same-session long-side move available after each exit.

    This is a diagnostic for "did we exit before the trend resumed?" It stays in
    the research runner because it needs future bars and must not affect strategy
    decisions.
    """
    zone = ZoneInfo(timezone)
    annotated_trades: list[ClosedTrade] = []
    for trade in closed_trades:
        exit_local_date = trade.exited_at_utc.astimezone(zone).date()
        future_same_session_prices = (
            Decimal(str(bar.high if trade.entry_side == OrderSide.BUY else bar.low))
            for bar in bars
            if bar.timestamp_utc >= trade.exited_at_utc
            and bar.timestamp_utc.astimezone(zone).date() == exit_local_date
        )
        if trade.entry_side == OrderSide.BUY:
            best_future_price = max(future_same_session_prices, default=trade.exit_price)
            post_exit_move = (
                max(best_future_price - trade.exit_price, Decimal("0")) * trade.quantity
            )
        else:
            best_future_price = min(future_same_session_prices, default=trade.exit_price)
            post_exit_move = (
                max(trade.exit_price - best_future_price, Decimal("0")) * trade.quantity
            )
        annotated_trades.append(
            replace(
                trade,
                post_exit_max_favorable_pnl=post_exit_move,
            )
        )
    return annotated_trades


def with_macro_event_tags(
    closed_trades: list[ClosedTrade],
    *,
    timezone: str,
) -> list[ClosedTrade]:
    """Attach scheduled macro event tags to each completed trade.

    The lookup is intentionally applied after fills are complete. That keeps the
    fixture as research context instead of a hidden strategy input.
    """
    zone = ZoneInfo(timezone)
    calendar = default_macro_event_calendar()
    tagged_trades: list[ClosedTrade] = []
    for trade in closed_trades:
        local_date = trade.exited_at_utc.astimezone(zone).date()
        tagged_trades.append(
            replace(
                trade,
                macro_event_labels=calendar.labels_for_date(local_date),
            )
        )
    return tagged_trades


def enrich_closed_trades(
    closed_trades: list[ClosedTrade],
    *,
    bars: Sequence[Bar],
    timezone: str,
) -> list[ClosedTrade]:
    """Apply all post-trade enrichment steps in the canonical order.

    Order matters: post-exit move uses raw bars, regime tags derive session
    buckets from bars, signal-bar quality tags read bars by entry session, and
    macro tags attach scheduled event labels by exit session.
    """
    closed_trades = with_post_exit_max_favorable_pnl(
        closed_trades,
        bars=bars,
        timezone=timezone,
    )
    closed_trades = _with_regime_tags(
        closed_trades,
        bars=bars,
        timezone=timezone,
    )
    closed_trades = _with_signal_bar_quality_tags(
        closed_trades,
        bars=bars,
        timezone=timezone,
    )
    closed_trades = with_macro_event_tags(closed_trades, timezone=timezone)
    return closed_trades


__all__ = [
    "enrich_closed_trades",
    "with_macro_event_tags",
    "with_post_exit_max_favorable_pnl",
]
