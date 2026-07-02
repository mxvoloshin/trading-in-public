"""Swing / multi-day signal generators for the SPY multi-timeframe track.

Every generator returns ``trade_vectorbt.Signals`` (boolean entries/exits) and,
unlike the intraday generators, is allowed to **hold overnight and across days**.
The one discipline they all share is *no lookahead*: an indicator computed from a
bar's close can only be acted on the following bar, so :func:`finalize_swing`
shifts the raw signals forward one bar (vectorbt fills at the signal bar's close,
so a one-bar shift models "decide after this close, execute at the next bar").

The families here are the ones the market-structure analysis motivates for SPY:

- **Trend / regime filter** (``sma_trend``) -- ride the primary uptrend, step
  aside below a long moving average.
- **Momentum crossover** (``ma_cross``).
- **Pullback mean-reversion in an uptrend** (``rsi2_meanrev``) -- the classic
  Connors RSI(2) idea: buy dips only while price is above its 200-day average.
- **Breakout** (``donchian_breakout``).
- **Buy-the-dip** (``dip_buy``) -- enter after consecutive down closes.
- **Overnight hold** (``overnight_hold``) -- capture SPY's overnight drift by
  holding only from each close to the next open (intraday frames only).
- **Buy & hold** (``buy_and_hold``) -- the benchmark every timing rule must beat.
"""

from __future__ import annotations

import pandas as pd
from trade_vectorbt import Signals

MARKET_TZ = "America/New_York"


def _dates(df: pd.DataFrame) -> pd.Series:
    """Market-local trade date per bar (from the precomputed helper column)."""
    if "date" in df.columns:
        return df["date"]
    local = df.index.tz_convert(MARKET_TZ)
    return pd.Series(local.date, index=df.index)


def finalize_swing(entries: pd.Series, exits: pd.Series, *, shift: bool = True) -> Signals:
    """Apply the no-lookahead one-bar shift and return a clean ``Signals`` pair.

    Swing strategies carry positions across days, so there is *no* EOD flatten
    and *no* per-day masking here -- that is the whole point of this track. The
    only transform is the forward shift so a signal derived from a bar's close is
    executed on the next bar, never the same bar.
    """
    if shift:
        entries = entries.shift(1, fill_value=False)
        exits = exits.shift(1, fill_value=False)
    return Signals(
        entries=entries.fillna(False).astype(bool),
        exits=exits.fillna(False).astype(bool),
    )


def _rsi(close: pd.Series, window: int) -> pd.Series:
    """Wilder's RSI. Small helper so we don't depend on vectorbt's indicator API.

    Uses an exponential (Wilder) average of gains/losses, the standard RSI
    definition Connors' RSI(2) system assumes.
    """
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(alpha=1.0 / window, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def buy_and_hold(df: pd.DataFrame) -> Signals:
    """Benchmark: buy the first bar, never sell. Pure SPY exposure.

    This is the number every timing strategy must beat -- for a strong-trend
    instrument like SPY it is a genuinely hard benchmark, not a straw man.
    """
    entries = pd.Series(False, index=df.index)
    entries.iloc[0] = True
    exits = pd.Series(False, index=df.index)
    # No shift: buying the very first available bar needs no future information.
    return finalize_swing(entries, exits, shift=False)


def sma_trend(df: pd.DataFrame, *, window: int = 200) -> Signals:
    """Long while close is above its ``window``-bar SMA, flat below it.

    A regime filter: stay invested during the primary uptrend, step aside when
    price loses its long average. Aims to keep most of buy & hold's upside while
    dodging the deepest drawdowns.
    """
    close = df["close"]
    sma = close.rolling(window).mean()
    above = (close > sma).fillna(False)
    entries = above & ~above.shift(1, fill_value=False)  # cross up
    exits = ~above & above.shift(1, fill_value=False)  # cross down
    return finalize_swing(entries, exits)


def ma_cross(df: pd.DataFrame, *, fast: int = 20, slow: int = 100) -> Signals:
    """Momentum: long when the fast SMA is above the slow SMA."""
    close = df["close"]
    fast_ma = close.rolling(fast).mean()
    slow_ma = close.rolling(slow).mean()
    long = (fast_ma > slow_ma).fillna(False)
    entries = long & ~long.shift(1, fill_value=False)
    exits = ~long & long.shift(1, fill_value=False)
    return finalize_swing(entries, exits)


def rsi2_meanrev(
    df: pd.DataFrame,
    *,
    trend_window: int = 200,
    rsi_window: int = 2,
    entry_rsi: float = 10.0,
    exit_sma: int = 5,
) -> Signals:
    """Connors-style pullback: buy oversold dips *only* in an uptrend.

    Entry: close is above its ``trend_window`` SMA (uptrend regime) **and** the
    short RSI is below ``entry_rsi`` (a sharp pullback). Exit: close closes back
    above its short ``exit_sma`` SMA (the bounce has played out). Long-only,
    holds a few days on average.
    """
    close = df["close"]
    trend = close.rolling(trend_window).mean()
    rsi = _rsi(close, rsi_window)
    fast_sma = close.rolling(exit_sma).mean()
    in_uptrend = close > trend
    entries = (in_uptrend & (rsi < entry_rsi)).fillna(False)
    exits = (close > fast_sma).fillna(False)
    return finalize_swing(entries, exits)


def donchian_breakout(
    df: pd.DataFrame, *, entry_window: int = 20, exit_window: int = 10
) -> Signals:
    """Breakout: long a new ``entry_window``-bar high, exit a ``exit_window``-bar low.

    The channel is built from *prior* bars only (``shift(1)`` before the rolling
    max/min) so the current bar is compared against history it could actually
    have known, and :func:`finalize_swing` adds the execution shift on top.
    """
    high, low, close = df["high"], df["low"], df["close"]
    upper = high.shift(1).rolling(entry_window).max()
    lower = low.shift(1).rolling(exit_window).min()
    entries = (close > upper).fillna(False)
    exits = (close < lower).fillna(False)
    return finalize_swing(entries, exits)


def dip_buy(df: pd.DataFrame, *, down_days: int = 3, trend_window: int = 200) -> Signals:
    """Buy after ``down_days`` consecutive lower closes in an uptrend; exit on an up close.

    A simpler cousin of the RSI(2) system: consecutive down closes proxy an
    oversold pullback. The trend filter keeps it from catching falling knives in
    a bear market. Exit on the first higher close (the bounce).
    """
    close = df["close"]
    trend = close.rolling(trend_window).mean()
    down = close < close.shift(1)
    # All of the last ``down_days`` closes were down.
    streak = down
    for k in range(1, down_days):
        streak = streak & down.shift(k, fill_value=False)
    entries = (streak & (close > trend)).fillna(False)
    exits = (close > close.shift(1)).fillna(False)
    return finalize_swing(entries, exits)


def overnight_hold(df: pd.DataFrame) -> Signals:
    """Hold only overnight: enter on each day's last bar, exit on the next day's first bar.

    Designed for **intraday** frames (15m/1h). The prior intraday study showed
    that essentially all of SPY's drift accrued overnight, so this isolates that
    move: buy the closing bar (a market-on-close decision needs no future info)
    and sell the opening bar of the following session. No shift -- both signals
    are deterministic time-of-day rules, not indicator reactions.
    """
    dates = _dates(df)
    last_bar = ~dates.duplicated(keep="last")  # final bar of each trade date
    first_bar = ~dates.duplicated(keep="first")  # first bar of each trade date
    entries = pd.Series(last_bar.to_numpy(), index=df.index)
    exits = pd.Series(first_bar.to_numpy(), index=df.index)
    return finalize_swing(entries, exits, shift=False)


__all__ = [
    "buy_and_hold",
    "dip_buy",
    "donchian_breakout",
    "finalize_swing",
    "ma_cross",
    "overnight_hold",
    "rsi2_meanrev",
    "sma_trend",
]
