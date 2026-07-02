"""Intraday, flat-by-EOD signal generators for the SPY research track.

All generators return ``trade_vectorbt.Signals`` (boolean entries/exits) and
share two invariants enforced by :func:`finalize_intraday`:

1. **No lookahead.** Raw signals are computed from a bar's own close, then
   shifted forward one bar so execution happens on the *next* bar — you never
   trade on information from a bar you haven't finished observing. (VectorBT
   fills at the signal bar's close, so a one-bar shift approximates a realistic
   next-bar fill.)
2. **Intraday only / flat by EOD.** Entries are blocked near the close and a
   forced exit fires at the flatten bar, so no position is ever carried
   overnight. This is what the research goal requires (intraday shares, flat by
   end of day) and it deliberately forgoes SPY's overnight drift.

These build on the existing ``trade_vectorbt`` reference generators but add the
intraday discipline the reference ones lack.
"""

from __future__ import annotations

from datetime import time as dt_time

import numpy as np
import pandas as pd
from trade_vectorbt import Signals

MARKET_TZ = "America/New_York"
FLATTEN_TIME = dt_time(15, 55)  # last bar of the RTH session (15:55 -> 16:00)
LAST_ENTRY_TIME = dt_time(15, 45)  # block entries in the final 10 min


def _local_times(df: pd.DataFrame) -> pd.Series:
    """Market-local time-of-day for each bar (from the precomputed helper col)."""
    if "time" in df.columns:
        return df["time"]
    local = df.index.tz_convert(MARKET_TZ)
    return pd.Series(local.time, index=df.index)


def _local_dates(df: pd.DataFrame) -> pd.Series:
    if "date" in df.columns:
        return df["date"]
    local = df.index.tz_convert(MARKET_TZ)
    return pd.Series(local.date, index=df.index)


def finalize_intraday(
    entries: pd.Series,
    exits: pd.Series,
    df: pd.DataFrame,
    *,
    last_entry_time: dt_time = LAST_ENTRY_TIME,
    flatten_time: dt_time = FLATTEN_TIME,
    shift: bool = True,
) -> Signals:
    """Apply the no-lookahead shift + intraday/EOD-flat discipline to raw signals.

    Steps (order matters):
    1. Shift entries/exits forward one bar (execute next bar, not the signal
       bar) to remove same-bar lookahead. The shift is masked to same-day so a
       late signal never leaks across the overnight gap.
    2. Block entries at/after ``last_entry_time`` (no fresh risk into the close).
    3. Force an exit on every bar at/after ``flatten_time`` so any open position
       is closed by end of day.
    """
    times = _local_times(df)
    dates = _local_dates(df)

    if shift:
        # Shift within each day; the first bar of a day gets False (no carry-in).
        entries = entries.groupby(dates).shift(1, fill_value=False).astype(bool)
        exits = exits.groupby(dates).shift(1, fill_value=False).astype(bool)

    # No new entries into the close.
    entries = entries & (times < last_entry_time)

    # Force flat at/after the flatten bar.
    eod = times >= flatten_time
    exits = exits | eod

    return Signals(entries=entries.fillna(False), exits=exits.fillna(False))


def buy_open_sell_close_signals(df: pd.DataFrame) -> Signals:
    """Benchmark: buy the first bar each day, sell at the close. Intraday beta.

    This captures the pure open-to-close move with no timing skill — the bar
    every real intraday strategy must clear to be worth trading.
    """
    times = _local_times(df)
    dates = _local_dates(df)
    # Enter on the first bar of each day (9:30). No shift: this is a benchmark
    # that intentionally buys the opening bar; exit is the EOD flatten.
    first_bar = ~dates.duplicated(keep="first")
    entries = pd.Series(first_bar.values, index=df.index) & (times < LAST_ENTRY_TIME)
    exits = pd.Series(False, index=df.index)
    return finalize_intraday(entries, exits, df, shift=False)


def rsi_meanrev_signals(
    df: pd.DataFrame,
    *,
    window: int = 14,
    lower: float = 30.0,
    exit_level: float = 55.0,
) -> Signals:
    """Intraday RSI mean-reversion (theory: weak negative 5-min autocorrelation).

    Buy when RSI dips below ``lower`` (oversold), exit when it recovers past
    ``exit_level`` or at EOD. Long-only. RSI is computed on the continuous close
    series; the warmup NaNs simply produce no early signals.
    """
    import vectorbt as vbt

    close = df["close"]
    rsi = vbt.RSI.run(close, window=window).rsi
    entries = (rsi < lower).fillna(False)
    exits = (rsi > exit_level).fillna(False)
    return finalize_intraday(entries, exits, df)


def zscore_meanrev_signals(
    df: pd.DataFrame,
    *,
    window: int = 20,
    entry_z: float = -1.5,
    exit_z: float = 0.0,
) -> Signals:
    """Intraday z-score mean-reversion around a rolling VWAP-like mean.

    Buy when price is ``entry_z`` standard deviations below its rolling mean,
    exit when it reverts to ``exit_z`` or at EOD. A simple, explainable
    counterpart to the RSI variant, using price distance rather than a
    momentum oscillator.
    """
    close = df["close"]
    ma = close.rolling(window).mean()
    sd = close.rolling(window).std()
    z = (close - ma) / sd
    entries = (z < entry_z).fillna(False)
    exits = (z > exit_z).fillna(False)
    return finalize_intraday(entries, exits, df)


def orb_breakout_signals(df: pd.DataFrame, *, opening_range_bars: int = 6) -> Signals:
    """Opening-range breakout: long when close exceeds the first-N-bar high.

    Momentum/continuation hypothesis. Exit on a fall back below the opening
    range midpoint or at EOD. One entry per day.
    """
    high, low, close = df["high"], df["low"], df["close"]
    dates = _local_dates(df)
    or_high = pd.Series(np.nan, index=df.index)
    or_mid = pd.Series(np.nan, index=df.index)
    for _d, g in df.groupby(dates):
        if len(g) < opening_range_bars:
            continue
        h = high.loc[g.index[:opening_range_bars]].max()
        low_ = low.loc[g.index[:opening_range_bars]].min()
        or_high.loc[g.index] = h
        or_mid.loc[g.index] = (h + low_) / 2.0
    raw = (close > or_high) & or_high.notna()
    # first breakout per day only
    first = raw & (raw.groupby(dates).cumsum() == 1)
    exits = ((close <= or_mid) & or_mid.notna()).fillna(False)
    return finalize_intraday(first.fillna(False), exits, df)


def orb_fade_signals(df: pd.DataFrame, *, opening_range_bars: int = 6) -> Signals:
    """Opening-range fade: short the first break of the range low's *high* side.

    Contrarian counterpart to ORB — motivated by the weak breakout continuation
    (~55%) and slight mean-reversion. Long-only implementation: buy the first
    break *below* the opening-range low (fade the downside break, betting on
    reversion back into the range), exit at the range midpoint or EOD.
    """
    high, low, close = df["high"], df["low"], df["close"]
    dates = _local_dates(df)
    or_low = pd.Series(np.nan, index=df.index)
    or_mid = pd.Series(np.nan, index=df.index)
    for _d, g in df.groupby(dates):
        if len(g) < opening_range_bars:
            continue
        h = high.loc[g.index[:opening_range_bars]].max()
        low_ = low.loc[g.index[:opening_range_bars]].min()
        or_low.loc[g.index] = low_
        or_mid.loc[g.index] = (h + low_) / 2.0
    raw = (close < or_low) & or_low.notna()
    first = raw & (raw.groupby(dates).cumsum() == 1)
    exits = ((close >= or_mid) & or_mid.notna()).fillna(False)
    return finalize_intraday(first.fillna(False), exits, df)


def ma_cross_intraday_signals(df: pd.DataFrame, *, fast: int = 9, slow: int = 21) -> Signals:
    """Intraday MA crossover (momentum). Long when fast>slow, flat otherwise."""
    import vectorbt as vbt

    close = df["close"]
    fast_ma = vbt.MA.run(close, window=fast).ma
    slow_ma = vbt.MA.run(close, window=slow).ma
    entries = fast_ma.vbt.crossed_above(slow_ma)
    exits = fast_ma.vbt.crossed_below(slow_ma)
    return finalize_intraday(entries.fillna(False), exits.fillna(False), df)


__all__ = [
    "FLATTEN_TIME",
    "LAST_ENTRY_TIME",
    "buy_open_sell_close_signals",
    "finalize_intraday",
    "ma_cross_intraday_signals",
    "orb_breakout_signals",
    "orb_fade_signals",
    "rsi_meanrev_signals",
    "zscore_meanrev_signals",
]
