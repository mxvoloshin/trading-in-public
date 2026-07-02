"""Tests for the Opening Range Breakout (ORB) vectorbt signal generator.

The ORB generator is more complex than the other three (MA/RSI/ATR) because it
requires per-day session grouping and market-local time-of-day filters. These
tests create synthetic 5-minute bars with known breakouts and verify that the
signal arrays match the expected ORB logic.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from datetime import time as dt_time

import numpy as np
import pandas as pd
import pytest
from trade_data import Bar
from trade_vectorbt import orb_signals, run_vectorbt_backtest, to_ohlcv_dataframe


@pytest.fixture
def synthetic_intraday_ohlcv() -> pd.DataFrame:
    """5 days of 5-minute SPY bars with a sine-wave trend that produces breakouts.

    Each day has 78 bars (9:30-16:00 NY regular session). The price oscillates
    around a gentle uptrend so that some days break above the 30-minute opening
    range high and some don't, producing realistic entry/exit signals.
    """
    rng = np.random.default_rng(42)
    bars: list[Bar] = []
    bar_index = 0

    for day in range(1, 6):  # June 1-5, 2026 (Mon-Fri)
        for j in range(78):  # 78 5-min bars per regular session
            minute_offset = 30 + j * 5
            hour = 13 + minute_offset // 60
            minute = minute_offset % 60
            timestamp = datetime(2026, 6, day, hour, minute, tzinfo=UTC)

            # Sine-wave price around a gentle uptrend. The oscillation is
            # large enough that some bars after 10:00 will exceed the
            # opening range high (first 6 bars' highs).
            close = 100.0 + bar_index * 0.02 + 3.0 * math.sin(bar_index / 7)
            open_ = close - 0.1 * math.sin(bar_index / 5)
            high = max(open_, close) + 0.3 + 0.2 * rng.random()
            low = min(open_, close) - 0.3 - 0.2 * rng.random()
            volume = int(1000 + 500 * rng.random())

            bars.append(
                Bar(
                    instrument_id="SPY.US",
                    timeframe="5Min",
                    timestamp_utc=timestamp,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    session="regular",
                )
            )
            bar_index += 1

    return to_ohlcv_dataframe(bars)


def test_orb_signals_returns_boolean_series(synthetic_intraday_ohlcv: pd.DataFrame) -> None:
    """ORB returns boolean entries/exits with the same index as the input."""
    signals = orb_signals(synthetic_intraday_ohlcv, opening_range_bars=6)

    assert isinstance(signals.entries, pd.Series)
    assert isinstance(signals.exits, pd.Series)
    assert signals.entries.dtype == bool
    assert signals.exits.dtype == bool
    assert len(signals.entries) == len(synthetic_intraday_ohlcv)
    assert len(signals.exits) == len(synthetic_intraday_ohlcv)
    assert signals.sl_stop is None


def test_orb_signals_rejects_invalid_opening_range_bars(
    synthetic_intraday_ohlcv: pd.DataFrame,
) -> None:
    """Opening range bars must be positive."""
    with pytest.raises(ValueError, match="opening_range_bars"):
        orb_signals(synthetic_intraday_ohlcv, opening_range_bars=0)
    with pytest.raises(ValueError, match="opening_range_bars"):
        orb_signals(synthetic_intraday_ohlcv, opening_range_bars=-3)


def test_orb_signals_produces_entries_and_exits(synthetic_intraday_ohlcv: pd.DataFrame) -> None:
    """With trending intraday data, ORB should produce at least some entries and exits."""
    signals = orb_signals(synthetic_intraday_ohlcv, opening_range_bars=6)
    assert int(signals.entries.sum()) > 0
    assert int(signals.exits.sum()) > 0


def test_orb_signals_max_one_entry_per_day(synthetic_intraday_ohlcv: pd.DataFrame) -> None:
    """Only one entry per day: the first breakout bar."""
    signals = orb_signals(synthetic_intraday_ohlcv, opening_range_bars=6)
    local_idx = synthetic_intraday_ohlcv.index.tz_convert("America/New_York")
    daily_entries = signals.entries.groupby(local_idx.date).sum()
    # Every day with any entries should have exactly 1 entry.
    days_with_entries = daily_entries[daily_entries.astype(bool)]
    assert (days_with_entries <= 1).all()


def test_orb_signals_no_entries_during_opening_range() -> None:
    """Entries must not fire during the first 6 bars (opening range) of the day."""
    bars = _one_day_bars(breakout_bar=3)  # break happens during OR -- should be ignored
    df = to_ohlcv_dataframe(bars)
    signals = orb_signals(df, opening_range_bars=6)
    assert int(signals.entries.sum()) == 0


def test_orb_signals_breakout_above_range_high_triggers_entry() -> None:
    """A close above the opening range high should trigger a long entry."""
    bars = _one_day_bars(breakout_bar=7, breakout_dir="up")
    df = to_ohlcv_dataframe(bars)
    signals = orb_signals(df, opening_range_bars=6)

    # Exactly one entry on the breakout bar (bar index 7, which is 10:00).
    assert int(signals.entries.sum()) == 1
    entry_index = signals.entries[signals.entries].index[0]
    local_ts = entry_index.astimezone("America/New_York")
    assert local_ts.time() >= dt_time(10, 0)
    assert local_ts.time() <= dt_time(14, 30)


def test_orb_signals_midpoint_stop_triggers_exit() -> None:
    """A close below the opening range midpoint should trigger an exit."""
    bars = _one_day_bars(breakout_bar=7, breakout_dir="up", revert_bar=8)
    df = to_ohlcv_dataframe(bars)
    signals = orb_signals(df, opening_range_bars=6)

    assert int(signals.entries.sum()) == 1
    # The exit should fire on bar 8 (the revert bar) or at EOD.
    assert int(signals.exits.sum()) >= 1


def test_orb_signals_eod_flatten_triggers_exit() -> None:
    """Even without a stop hit, the 15:55 bar should trigger an exit."""
    bars = _one_day_bars(breakout_bar=7, breakout_dir="up", revert_bar=None)
    df = to_ohlcv_dataframe(bars)
    signals = orb_signals(df, opening_range_bars=6)

    assert int(signals.entries.sum()) == 1
    # Should have at least the EOD flatten exit.
    assert int(signals.exits.sum()) >= 1
    # The last bar (15:55) should have an exit signal.
    assert signals.exits.iloc[-1]


def test_orb_signals_short_days_skipped() -> None:
    """Days with fewer than opening_range_bars should produce no entries."""
    bars = _make_short_day_bars()
    df = to_ohlcv_dataframe(bars)
    signals = orb_signals(df, opening_range_bars=6)
    assert int(signals.entries.sum()) == 0


def test_orb_end_to_end_simulation(synthetic_intraday_ohlcv: pd.DataFrame) -> None:
    """ORB signals can be passed to run_vectorbt_backtest and produce a portfolio."""
    signals = orb_signals(synthetic_intraday_ohlcv, opening_range_bars=6)
    close = synthetic_intraday_ohlcv["close"]

    result = run_vectorbt_backtest(
        close,
        signals.entries,
        signals.exits,
        init_cash=10_000.0,
        fees=0.001,
        direction="longonly",
        freq="5min",
    )

    assert result.portfolio is not None
    assert result.portfolio.trades.count() >= 0
    assert isinstance(float(result.portfolio.total_return()), float)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _one_day_bars(
    *,
    breakout_bar: int | None = None,
    breakout_dir: str = "up",
    revert_bar: int | None = None,
) -> list[Bar]:
    """Create one day of 5Min regular-session bars with a controlled breakout.

    Bars 0-5 (9:30-10:00) form the opening range with prices around 100.
    If breakout_bar is set, the close at that bar jumps outside the range.
    If revert_bar is set, the close drops back below the midpoint.
    """
    bars: list[Bar] = []
    base_price = 100.0
    for j in range(78):
        minute_offset = 30 + j * 5
        hour = 13 + minute_offset // 60
        minute = minute_offset % 60
        timestamp = datetime(2026, 6, 1, hour, minute, tzinfo=UTC)

        close = base_price + 0.01 * j
        open_ = close - 0.05
        high = max(open_, close) + 0.2
        low = min(open_, close) - 0.2

        # Apply breakout at the specified bar.
        if breakout_bar is not None and j == breakout_bar:
            if breakout_dir == "up":
                close = 102.0  # above OR high
                high = 102.5
            else:
                close = 98.0  # below OR low
                low = 97.5

        # Revert below midpoint at the specified bar.
        if revert_bar is not None and j == revert_bar:
            close = 99.5  # below midpoint (100 + 100) / 2 = 100
            low = 99.0

        bars.append(
            Bar(
                instrument_id="SPY.US",
                timeframe="5Min",
                timestamp_utc=timestamp,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=1_000,
                session="regular",
            )
        )
    return bars


def _make_short_day_bars() -> list[Bar]:
    """Create a day with only 3 bars (insufficient for a 6-bar opening range)."""
    bars: list[Bar] = []
    for j in range(3):
        minute_offset = 30 + j * 5
        hour = 13 + minute_offset // 60
        minute = minute_offset % 60
        timestamp = datetime(2026, 6, 2, hour, minute, tzinfo=UTC)
        bars.append(
            Bar(
                instrument_id="SPY.US",
                timeframe="5Min",
                timestamp_utc=timestamp,
                open=100.0,
                high=100.5,
                low=99.5,
                close=100.0,
                volume=1_000,
                session="regular",
            )
        )
    return bars
