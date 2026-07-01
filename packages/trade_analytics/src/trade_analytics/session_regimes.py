"""Session regime tags: gap, opening range, trend, and volume buckets.

Derived from normalized OHLCV bars for each market-local session. These tags
are reporting-only — they explain the backtest without becoming implicit
strategy inputs. The public entry point is ``session_regime_tags``, which
returns one ``SessionRegimeTags`` per market-local date.

Depends on ``trade_data`` for the ``Bar`` record and on ``trade_analytics.metrics``
for ``ClosedTrade`` (used by the enrichment helpers that attach tags to trades).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from zoneinfo import ZoneInfo

from trade_data import Bar

from trade_analytics.metrics import ClosedTrade


@dataclass(frozen=True, slots=True)
class SessionRegimeTags:
    """Reporting-only tags derived from one market-local session."""

    gap_bucket: str
    opening_range_state: str
    opening_range_pct_bucket: str
    opening_drive_return_bucket: str
    opening_drive_close_position_bucket: str
    daily_trend_state: str
    relative_volume_bucket: str


def _with_regime_tags(
    closed_trades: list[ClosedTrade],
    *,
    bars: Sequence[Bar],
    timezone: str,
) -> list[ClosedTrade]:
    """Attach session regime tags to each completed trade.

    The tags are calculated after execution so they can explain the backtest
    without becoming implicit strategy inputs.
    """
    zone = ZoneInfo(timezone)
    session_tags = session_regime_tags(bars, timezone=timezone)
    tagged_trades: list[ClosedTrade] = []
    for trade in closed_trades:
        local_date = trade.exited_at_utc.astimezone(zone).date().isoformat()
        tags = session_tags.get(
            local_date,
            SessionRegimeTags(
                gap_bucket="unknown_gap",
                opening_range_state="unknown_opening_range",
                opening_range_pct_bucket="unknown_opening_range_pct",
                opening_drive_return_bucket="unknown_opening_drive_return",
                opening_drive_close_position_bucket="unknown_opening_drive",
                daily_trend_state="unknown_daily_trend",
                relative_volume_bucket="unknown_relative_volume",
            ),
        )
        tagged_trades.append(
            replace(
                trade,
                gap_bucket=tags.gap_bucket,
                opening_range_state=tags.opening_range_state,
                opening_range_pct_bucket=tags.opening_range_pct_bucket,
                opening_drive_return_bucket=tags.opening_drive_return_bucket,
                opening_drive_close_position_bucket=tags.opening_drive_close_position_bucket,
                daily_trend_state=tags.daily_trend_state,
                relative_volume_bucket=tags.relative_volume_bucket,
            )
        )
    return tagged_trades


def _with_signal_bar_quality_tags(
    closed_trades: list[ClosedTrade],
    *,
    bars: Sequence[Bar],
    timezone: str,
) -> list[ClosedTrade]:
    """Attach signal-bar shape buckets to each completed trade."""
    zone = ZoneInfo(timezone)
    session_bars = _bars_by_local_date(bars, timezone=timezone)
    tagged_trades: list[ClosedTrade] = []
    for trade in closed_trades:
        entry_local_date = trade.entered_at_utc.astimezone(zone).date().isoformat()
        bars_for_date = session_bars.get(entry_local_date, [])
        signal_bar = next(
            (bar for bar in reversed(bars_for_date) if bar.timestamp_utc < trade.entered_at_utc),
            None,
        )
        close_location_bucket, body_pct_bucket = _signal_bar_quality_buckets(signal_bar)
        tagged_trades.append(
            replace(
                trade,
                signal_bar_close_location_bucket=close_location_bucket,
                signal_bar_body_pct_bucket=body_pct_bucket,
            )
        )
    return tagged_trades


def _signal_bar_quality_buckets(bar: Bar | None) -> tuple[str, str]:
    """Return close-location and body-size buckets for one signal bar."""
    if bar is None:
        return "unknown_signal_bar_close_location", "unknown_signal_bar_body_pct"
    high = Decimal(str(bar.high))
    low = Decimal(str(bar.low))
    signal_range = high - low
    if signal_range == 0:
        close_location = Decimal("0.50")
        body_pct = Decimal("0")
    else:
        close = Decimal(str(bar.close))
        open_price = Decimal(str(bar.open))
        close_location = (close - low) / signal_range
        body_pct = abs(close - open_price) / signal_range
    return _zero_to_one_bucket(
        close_location,
        unknown_label="unknown_signal_bar_close_location",
    ), _zero_to_one_bucket(body_pct, unknown_label="unknown_signal_bar_body_pct")


def session_regime_tags(
    bars: Sequence[Bar],
    *,
    timezone: str,
) -> dict[str, SessionRegimeTags]:
    """Derive simple session tags from normalized OHLCV bars."""
    zone = ZoneInfo(timezone)
    session_bars = _bars_by_local_date(bars, timezone=timezone)
    trailing_opening_volumes: list[Decimal] = []
    completed_session_closes: list[Decimal] = []
    previous_close: Decimal | None = None
    tags_by_date: dict[str, SessionRegimeTags] = {}

    for local_date, bars_for_date in sorted(session_bars.items()):
        current_open = Decimal(str(bars_for_date[0].open))
        current_close = Decimal(str(bars_for_date[-1].close))
        opening_window_volume = _opening_window_volume(bars_for_date, zone=zone)
        tags_by_date[local_date] = SessionRegimeTags(
            gap_bucket=_gap_bucket(
                current_open=current_open,
                previous_close=previous_close,
            ),
            opening_range_state=_opening_range_state(
                bars_for_date,
                zone=zone,
            ),
            opening_range_pct_bucket=_opening_range_pct_bucket(
                bars_for_date,
                zone=zone,
            ),
            opening_drive_return_bucket=_opening_drive_return_bucket(
                bars_for_date,
                zone=zone,
            ),
            opening_drive_close_position_bucket=_opening_drive_close_position_bucket(
                bars_for_date,
                zone=zone,
            ),
            daily_trend_state=_daily_trend_state(completed_session_closes),
            relative_volume_bucket=_relative_volume_bucket(
                opening_window_volume=opening_window_volume,
                trailing_opening_volumes=trailing_opening_volumes,
            ),
        )
        previous_close = current_close
        completed_session_closes.append(current_close)
        if opening_window_volume is not None:
            trailing_opening_volumes.append(opening_window_volume)

    return tags_by_date


def _bars_by_local_date(
    bars: Sequence[Bar],
    *,
    timezone: str,
) -> dict[str, list[Bar]]:
    """Group bars into market-local sessions while preserving bar order."""
    zone = ZoneInfo(timezone)
    sessions: dict[str, list[Bar]] = {}
    for bar in bars:
        local_date = bar.timestamp_utc.astimezone(zone).date().isoformat()
        sessions.setdefault(local_date, []).append(bar)
    return {
        local_date: sorted(values, key=lambda value: value.timestamp_utc)
        for local_date, values in sessions.items()
    }


def _gap_bucket(
    *,
    current_open: Decimal,
    previous_close: Decimal | None,
) -> str:
    """Bucket the current session open versus the prior session close."""
    if previous_close is None or previous_close == 0:
        return "unknown_gap"
    gap_pct = (current_open - previous_close) / previous_close
    if gap_pct >= Decimal("0.005"):
        return "large_gap_up"
    if gap_pct >= Decimal("0.001"):
        return "gap_up"
    if gap_pct <= Decimal("-0.005"):
        return "large_gap_down"
    if gap_pct <= Decimal("-0.001"):
        return "gap_down"
    return "flat_gap"


def _opening_range_state(
    bars: Sequence[Bar],
    *,
    zone: ZoneInfo,
) -> str:
    """Classify price location after the first 30 regular-session minutes."""
    opening_bars = [
        bar
        for bar in bars
        if bar.timestamp_utc.astimezone(zone).time().hour == 9
        and bar.timestamp_utc.astimezone(zone).time().minute < 60
    ][:6]
    reference_bar = next(
        (bar for bar in bars if bar.timestamp_utc.astimezone(zone).time().hour >= 10),
        None,
    )
    if not opening_bars or reference_bar is None:
        return "unknown_opening_range"

    opening_high = max(Decimal(str(bar.high)) for bar in opening_bars)
    opening_low = min(Decimal(str(bar.low)) for bar in opening_bars)
    reference_close = Decimal(str(reference_bar.close))
    if reference_close > opening_high:
        return "above_opening_range"
    if reference_close < opening_low:
        return "below_opening_range"
    return "inside_opening_range"


def _opening_range_pct_bucket(
    bars: Sequence[Bar],
    *,
    zone: ZoneInfo,
) -> str:
    """Bucket opening-range width as a share of the 9:30 bar open."""
    opening_bars = [
        bar
        for bar in bars
        if bar.timestamp_utc.astimezone(zone).time().hour == 9
        and bar.timestamp_utc.astimezone(zone).time().minute < 60
    ][:6]
    if len(opening_bars) < 6:
        return "unknown_opening_range_pct"

    opening_open = Decimal(str(opening_bars[0].open))
    if opening_open == 0:
        return "unknown_opening_range_pct"
    opening_high = max(Decimal(str(bar.high)) for bar in opening_bars)
    opening_low = min(Decimal(str(bar.low)) for bar in opening_bars)
    opening_range_pct = (opening_high - opening_low) / opening_open
    if opening_range_pct <= Decimal("0.0025"):
        return "<= 0.25%"
    if opening_range_pct <= Decimal("0.0050"):
        return "0.25% to 0.50%"
    if opening_range_pct <= Decimal("0.0075"):
        return "0.50% to 0.75%"
    if opening_range_pct <= Decimal("0.0100"):
        return "0.75% to 1.00%"
    return "> 1.00%"


def _opening_drive_close_position_bucket(
    bars: Sequence[Bar],
    *,
    zone: ZoneInfo,
) -> str:
    """Bucket the first 30-minute close location within its high-low range."""
    opening_bars = [
        bar
        for bar in bars
        if bar.timestamp_utc.astimezone(zone).time().hour == 9
        and bar.timestamp_utc.astimezone(zone).time().minute < 60
    ][:6]
    if len(opening_bars) < 6:
        return "unknown_opening_drive"

    opening_high = max(Decimal(str(bar.high)) for bar in opening_bars)
    opening_low = min(Decimal(str(bar.low)) for bar in opening_bars)
    opening_close = Decimal(str(opening_bars[-1].close))
    if opening_high == opening_low:
        close_position = Decimal("0.5")
    else:
        close_position = (opening_close - opening_low) / (opening_high - opening_low)

    return _zero_to_one_bucket(close_position, unknown_label="unknown_opening_drive")


def _zero_to_one_bucket(value: Decimal, *, unknown_label: str) -> str:
    """Bucket a normalized 0-to-1 feature into 0.20-wide ranges."""
    if value < 0 or value > 1:
        return unknown_label
    if value < Decimal("0.20"):
        return "0.00-0.20"
    if value < Decimal("0.40"):
        return "0.20-0.40"
    if value < Decimal("0.60"):
        return "0.40-0.60"
    if value < Decimal("0.80"):
        return "0.60-0.80"
    return "0.80-1.00"


def _opening_drive_return_bucket(
    bars: Sequence[Bar],
    *,
    zone: ZoneInfo,
) -> str:
    """Bucket first-30-minute return using the research-plan thresholds."""
    opening_bars = [
        bar
        for bar in bars
        if bar.timestamp_utc.astimezone(zone).time().hour == 9
        and bar.timestamp_utc.astimezone(zone).time().minute < 60
    ][:6]
    if len(opening_bars) < 6:
        return "unknown_opening_drive_return"

    opening_open = Decimal(str(opening_bars[0].open))
    if opening_open == 0:
        return "unknown_opening_drive_return"
    opening_close = Decimal(str(opening_bars[-1].close))
    return_pct = (opening_close - opening_open) / opening_open
    if return_pct <= Decimal("-0.0050"):
        return "<= -0.50%"
    if return_pct < Decimal("-0.0020"):
        return "-0.50% to -0.20%"
    if return_pct < Decimal("0"):
        return "-0.20% to 0%"
    if return_pct <= Decimal("0.0020"):
        return "0% to +0.20%"
    if return_pct <= Decimal("0.0050"):
        return "+0.20% to +0.50%"
    return "> +0.50%"


def _opening_window_volume(
    bars: Sequence[Bar],
    *,
    zone: ZoneInfo,
) -> Decimal | None:
    """Return completed first-30-minute session volume."""
    opening_bars = [
        bar
        for bar in bars
        if bar.timestamp_utc.astimezone(zone).time().hour == 9
        and bar.timestamp_utc.astimezone(zone).time().minute < 60
    ][:6]
    if len(opening_bars) < 6:
        return None
    return sum((Decimal(bar.volume) for bar in opening_bars), Decimal("0"))


def _daily_trend_state(
    completed_session_closes: Sequence[Decimal],
    *,
    sma_period: int = 20,
    slope_lookback_sessions: int = 5,
) -> str:
    """Classify completed-daily trend context without using today's close."""
    required_closes = sma_period + slope_lookback_sessions
    if len(completed_session_closes) < required_closes:
        return "daily_context_not_ready"

    prior_regular_session_close = completed_session_closes[-1]
    daily_sma = _sma(
        values=completed_session_closes,
        period=sma_period,
        end_offset=0,
    )
    daily_sma_lookback = _sma(
        values=completed_session_closes,
        period=sma_period,
        end_offset=slope_lookback_sessions,
    )
    daily_sma_slope = daily_sma - daily_sma_lookback

    if prior_regular_session_close > daily_sma and daily_sma_slope >= 0:
        return "bullish_daily_context"
    if prior_regular_session_close < daily_sma and daily_sma_slope <= 0:
        return "bearish_daily_context"
    return "neutral_daily_context"


def _sma(
    *,
    values: Sequence[Decimal],
    period: int,
    end_offset: int,
) -> Decimal:
    """Calculate a simple moving average over a completed-value window."""
    end_index = len(values) - end_offset
    start_index = end_index - period
    window = values[start_index:end_index]
    return sum(window, Decimal("0")) / Decimal(period)


def _relative_volume_bucket(
    *,
    opening_window_volume: Decimal | None,
    trailing_opening_volumes: Sequence[Decimal],
) -> str:
    """Bucket opening-window RVOL against the prior 20 completed sessions."""
    if opening_window_volume is None:
        return "unknown_relative_volume"
    if len(trailing_opening_volumes) < 20:
        return "insufficient_rvol_history"
    trailing_window = trailing_opening_volumes[-20:]
    baseline = sum(trailing_window, Decimal("0")) / Decimal(len(trailing_window))
    if baseline == 0:
        return "unknown_relative_volume"
    relative_volume = opening_window_volume / baseline
    if relative_volume < Decimal("0.80"):
        return "dead"
    if relative_volume < Decimal("1.20"):
        return "normal"
    if relative_volume < Decimal("1.80"):
        return "active"
    return "event_like"


__all__ = [
    "SessionRegimeTags",
    "_with_regime_tags",
    "_with_signal_bar_quality_tags",
    "_signal_bar_quality_buckets",
    "session_regime_tags",
    "_bars_by_local_date",
    "_gap_bucket",
    "_opening_range_state",
    "_opening_range_pct_bucket",
    "_opening_drive_close_position_bucket",
    "_zero_to_one_bucket",
    "_opening_drive_return_bucket",
    "_opening_window_volume",
    "_daily_trend_state",
    "_sma",
    "_relative_volume_bucket",
]
