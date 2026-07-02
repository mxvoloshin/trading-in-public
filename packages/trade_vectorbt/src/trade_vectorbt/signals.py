"""Reference signal generators for fast strategy prototyping.

Each generator takes price data and returns a :class:`Signals` bundle - boolean
``entries``/``exits`` arrays (one value per bar) ready for
:func:`trade_vectorbt.runner.run_vectorbt_backtest`. They use vectorbt's
built-in indicators (MA, RSI, ATR) so a new idea can be tried in a few lines
without hand-coding the math.

These are *reference* generators: they demonstrate common patterns (MA
crossover, RSI mean-reversion, ATR trailing stop) and are meant to be copied or
extended, not to be complete trading systems.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import vectorbt as vbt


@dataclass(frozen=True, slots=True)
class Signals:
    """Entry/exit signal arrays for vectorbt's ``Portfolio.from_signals``.

    VectorBT drives portfolio simulation from boolean signal arrays (one value
    per bar). This dataclass bundles the arrays a signal generator produces so
    they can be unpacked into :func:`run_vectorbt_backtest` in one step::

        sig = ma_cross_signals(close, fast=10, slow=30)
        result = run_vectorbt_backtest(close, sig.entries, sig.exits, ...)
    """

    entries: pd.Series
    exits: pd.Series
    # Per-bar stop-loss as a fraction of price (e.g. 0.03 = 3%). When set,
    # pass it as the ``sl_stop`` argument to ``run_vectorbt_backtest``. None
    # for strategies that do not use a stop.
    sl_stop: pd.Series | None = None


def ma_cross_signals(
    close: pd.Series,
    *,
    fast: int,
    slow: int,
) -> Signals:
    """Long/short MA crossover: enter when fast crosses above slow, exit below.

    The simplest trend-following reference. With ``direction="both"`` in the
    runner, the exit signal flips to short; with ``direction="longonly"`` it
    just closes the long.

    Parameters:
        close: Close-price series with a tz-aware DatetimeIndex.
        fast: Short MA window (must be smaller than ``slow``).
        slow: Long MA window.
    """
    if fast >= slow:
        msg = f"fast window ({fast}) must be smaller than slow window ({slow})"
        raise ValueError(msg)
    fast_ma = vbt.MA.run(close, window=fast).ma
    slow_ma = vbt.MA.run(close, window=slow).ma
    # vectorbt 1.0 exposes crossover detection via the .vbt Series accessor,
    # not as a module-level function. crossed_above returns True on the bar
    # where fast rises above slow for the first time.
    entries = fast_ma.vbt.crossed_above(slow_ma)
    exits = fast_ma.vbt.crossed_below(slow_ma)
    return Signals(entries=entries, exits=exits)


def rsi_revert_signals(
    close: pd.Series,
    *,
    window: int,
    lower: float,
    upper: float,
) -> Signals:
    """RSI mean-reversion: enter long when RSI < lower, exit when RSI > upper.

    Buys oversold dips and exits when momentum normalises. A classic
    mean-reversion reference; pairs best with ``direction="longonly"``.

    Parameters:
        close: Close-price series with a tz-aware DatetimeIndex.
        window: RSI lookback window.
        lower: RSI level below which to enter (e.g. 30). Must be in [0, 100].
        upper: RSI level above which to exit (e.g. 70). Must be in [0, 100].
    """
    if not 0 <= lower <= 100:
        msg = f"lower threshold ({lower}) must be in [0, 100]"
        raise ValueError(msg)
    if not 0 <= upper <= 100:
        msg = f"upper threshold ({upper}) must be in [0, 100]"
        raise ValueError(msg)
    if lower >= upper:
        msg = f"lower ({lower}) must be below upper ({upper})"
        raise ValueError(msg)
    rsi = vbt.RSI.run(close, window=window).rsi
    entries = rsi < lower
    exits = rsi > upper
    return Signals(entries=entries, exits=exits)


def atr_trail_signals(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    *,
    window: int,
    multiplier: float,
) -> Signals:
    """ATR trailing-stop: always-in long with a volatility-scaled trailing stop.

    Enters after the ATR warmup period and exits only when the trailing stop
    fires. The stop distance is ``ATR * multiplier / close`` (a fraction of
    price), returned as ``sl_stop`` to be passed to
    :func:`run_vectorbt_backtest` with ``sl_trail=True``.

    Unlike MA/RSI which only need close, ATR requires high/low/close (true
    range uses the prior close). Pass the same-named columns from
    :func:`trade_vectorbt.adapter.to_ohlcv_dataframe`.

    Parameters:
        high: High-price series.
        low: Low-price series.
        close: Close-price series.
        window: ATR lookback window.
        multiplier: Stop distance as a multiple of ATR (e.g. 2.0 = 2x ATR).
            Must be positive.
    """
    if multiplier <= 0:
        msg = f"multiplier ({multiplier}) must be positive"
        raise ValueError(msg)
    atr = vbt.ATR.run(high, low, close, window=window).atr
    # vectorbt's sl_stop is a fraction of price (e.g. 0.03 = 3% below the
    # trailing high-water mark). Convert ATR (absolute price units) to a
    # fraction by dividing by close.
    sl_stop = (atr * multiplier) / close
    # Fill the ATR warmup NaNs so vectorbt's stop engine never sees a missing
    # value. The filled values during warmup are irrelevant because entries
    # are False there (no position is held). bfill().ffill() covers both the
    # leading warmup NaNs and any trailing gaps.
    sl_stop = sl_stop.bfill().ffill()
    # Enter only after the indicator has warmed up - entering during the NaN
    # period would mean holding a position with no valid stop reference.
    entries = pd.Series(False, index=close.index)
    entries.iloc[window:] = True
    exits = pd.Series(False, index=close.index)
    return Signals(entries=entries, exits=exits, sl_stop=sl_stop)


def orb_signals(
    df: pd.DataFrame,
    *,
    opening_range_bars: int = 6,
    market_tz: str = "America/New_York",
) -> Signals:
    """Opening Range Breakout (ORB): enter long when close exceeds the range high.

    Mirrors the existing SPY ORB strategy family in ``trade_strategies``: the
    opening range is defined as the first ``opening_range_bars`` regular-session
    bars (6 bars = 30 minutes of 5-minute data). The breakout enters long when
    the close exceeds the range high, exits when the close falls below the
    range midpoint stop, and force-flattens at 15:55 market time.

    Only one entry per day. Entries are allowed from the bar that completes the
    opening range (10:00 New York for 5-minute bars) through 14:30.

    This is a vectorized approximation of the existing bar-by-bar ORB engine.
    The existing engine checks intrabar extremes for stops (``bar.low <=
    stop``), fills at next-bar-open, and tracks per-trade MFE/MAE and
    R-multiples. VectorBT fills at the signal bar close, so the PnL from the two
    tracks is **not directly comparable** — see
    ``docs/architecture/vectorbt-integration-plan.md`` for fill-timing
    divergence.

    Parameters:
        df: OHLCV DataFrame with a tz-aware ``DatetimeIndex`` (the output of
            :func:`trade_vectorbt.adapter.to_ohlcv_dataframe`). Must contain
            ``high``, ``low``, and ``close`` columns.
        opening_range_bars: Number of bars that define the opening range. The
            default 6 = 30 minutes of 5-minute bars (matching the existing
            SPY ORB family).
        market_tz: IANA timezone for session/time-of-day logic. Defaults to
            ``"America/New_York"`` (XNYS / NYSE).
    """
    if opening_range_bars <= 0:
        msg = f"opening_range_bars ({opening_range_bars}) must be positive"
        raise ValueError(msg)

    high = df["high"]
    low = df["low"]
    close = df["close"]

    # Convert to market-local time for per-date grouping and time-of-day filters.
    local_idx = df.index.tz_convert(market_tz)
    local_dates = pd.Series(local_idx.date, index=df.index)
    local_times = pd.Series(local_idx.time, index=df.index)

    # Broadcast opening-range levels to every bar within each day. We compute
    # OR high/low/mid from only the first `opening_range_bars` bars per day,
    # then forward-fill across all bars in that day so the levels are visible
    # at every subsequent bar for signal generation.
    or_high = pd.Series(index=df.index, dtype=float)
    or_low = pd.Series(index=df.index, dtype=float)
    or_mid = pd.Series(index=df.index, dtype=float)

    for _date, group in df.groupby(local_dates):
        if len(group) < opening_range_bars:
            continue
        # Opening range is the first N bars of the regular session.
        or_h = high.loc[group.index[:opening_range_bars]].max()
        or_l = low.loc[group.index[:opening_range_bars]].min()
        or_high.loc[group.index] = or_h
        or_low.loc[group.index] = or_l
        or_mid.loc[group.index] = (or_h + or_l) / 2.0

    # Entry window: from bar that completes the opening range through 14:30.
    # For 5-min bars starting at 9:30, bar #6 starts at 10:00 — which is the
    # first bar eligible to enter (the opening range is now fully formed).
    # The 14:30 cutoff matches the existing engine's ``last_entry_bar``.
    from datetime import time as dt_time

    entry_start = dt_time(10, 0)
    last_entry = dt_time(14, 30)
    flatten_bar = dt_time(15, 55)

    in_entry_window = (local_times >= entry_start) & (local_times <= last_entry)

    # Raw breakout signal: close exceeds the opening range high.
    # ``or_high.notna()`` filters out days with insufficient bars for the range.
    raw_entries = (close > or_high) & in_entry_window & or_high.notna()

    # Only the first entry per day (max_trades_per_day = 1 in the existing engine).
    # cumsum within each day counts running True values; keeping only those
    # where the count is exactly 1 gives us just the first True per day.
    running_count = raw_entries.groupby(local_dates).cumsum()
    entries = raw_entries & (running_count == 1)

    # Exit: stop hit (close <= OR midpoint) OR end-of-day flatten at 15:55.
    # The stop is checked at bar close rather than at intrabar extremes (which
    # the existing engine uses). This is the fill-timing divergence noted above.
    stop_hit = (close <= or_mid) & or_mid.notna()
    eod_flatten = local_times >= flatten_bar
    exits = stop_hit | eod_flatten

    return Signals(entries=entries, exits=exits)


__all__ = [
    "Signals",
    "atr_trail_signals",
    "ma_cross_signals",
    "orb_signals",
    "rsi_revert_signals",
]
