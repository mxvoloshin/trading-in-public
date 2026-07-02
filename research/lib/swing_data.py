"""Data access for the SPY multi-timeframe / swing research track.

The intraday track (``data_access.py``) only ever needed 5-minute regular-session
bars from a single ~1-year window, so its loader hard-codes those assumptions.
The swing track is broader: it reads **daily bars over a decade** (2016->2026, so
it spans the 2018 Q4 selloff, the 2020 COVID crash and the 2022 bear) plus 1-hour
and 15-minute bars for the recent window, and it needs to *resample* intraday bars
into coarser session-aware timeframes. This module adds those capabilities while
still loading through the same ``trade_data`` store + ``trade_vectorbt`` adapter
seam the backtest engine uses (we never touch Alpaca directly).

Two things here are deliberately different from the intraday loader:

1. **Session parameter.** Daily bars are cached under the ``all`` session
   partition (their timestamp is midnight-ET, outside the 9:30-16:00 regular
   window), so the loader must be told which partition to read.
2. **Jump-based corruption cleaning.** The intraday cleaner flags a day whose
   *price level* deviates >50% from the global median. That is fine for a
   1-year window where the real price barely moves, but over 2016->2026 SPY
   genuinely trends from ~$200 to ~$745 -- a level test would false-flag the
   early years. Here we instead flag *implausible single-bar jumps* (SPY has
   never moved >35% in one session) and local spikes relative to a rolling
   median, which catches wrong-symbol / mis-adjusted cache segments without
   punishing the legitimate long-term trend.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from trade_data import HistoricalBarsRequest, Instrument, LocalMarketDataStore
from trade_data.sessions import get_market_session_config
from trade_vectorbt import to_ohlcv_dataframe

MARKET_TZ = "America/New_York"

# Which cached session partition each timeframe lives in. Daily bars are stored
# under "all" (their midnight-ET timestamp is outside the regular RTH window);
# intraday bars we fetched with --session regular.
DEFAULT_SESSION_FOR_TIMEFRAME: dict[str, str] = {
    "1Day": "all",
    "1Hour": "regular",
    "15Min": "regular",
    "5Min": "regular",
}


def load_bars_df(
    cache_dir: Path,
    *,
    symbol: str = "SPY",
    timeframe: str = "1Day",
    session: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Load normalized bars for one timeframe into a tz-aware OHLCV DataFrame.

    Returns a UTC-indexed frame with lowercase ``open/high/low/close/volume``
    columns plus market-local helper columns (``local_ts``, ``date``, ``time``)
    that every downstream analysis uses. ``session`` defaults to the right cache
    partition for the timeframe (see ``DEFAULT_SESSION_FOR_TIMEFRAME``).
    """
    if session is None:
        session = DEFAULT_SESSION_FOR_TIMEFRAME.get(timeframe, "regular")

    store = LocalMarketDataStore(cache_dir)
    instrument = Instrument.us_equity(symbol)
    session_config = get_market_session_config(instrument.market)

    # Default to a wide window; the store only returns partitions that exist.
    start = start or datetime(2000, 1, 1, tzinfo=UTC)
    end = end or datetime(2100, 1, 1, tzinfo=UTC)
    request = HistoricalBarsRequest(
        instrument=instrument,
        timeframe=timeframe,
        start_utc=start,
        end_utc=end,
        session=session,
    )
    bars = store.load_bars(request, session_config)
    if not bars:
        msg = f"no cached bars for {instrument.instrument_id} {timeframe} (session={session})"
        raise ValueError(msg)

    df = to_ohlcv_dataframe(bars)
    return _attach_local_columns(df)


def _attach_local_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Attach America/New_York helper columns (trade date + time-of-day)."""
    local = df.index.tz_convert(MARKET_TZ)
    df = df.copy()
    df["local_ts"] = local
    df["date"] = local.date
    df["time"] = local.time
    return df


def resample_session(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Resample intraday bars into a coarser timeframe, never spanning overnight.

    Grouping by trade date first guarantees a resampled bar never merges the
    last bars of one session with the first bars of the next (which would fabricate
    a bar straddling the overnight gap). Within a day we do a standard OHLCV
    aggregation: first open, max high, min low, last close, summed volume. Empty
    buckets (there is no trading at some offsets on short sessions) are dropped.

    ``rule`` is any pandas offset alias, e.g. ``"4h"`` or ``"2h"``. Daily data
    needs no resampling and should not be passed here.
    """
    out_frames: list[pd.DataFrame] = []
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    }
    for _date, g in df.groupby("date"):
        # origin="start" anchors buckets to the session's first bar so, e.g., a
        # 4h rule on a 9:30 open yields 9:30-13:30 and 13:30-16:00 buckets.
        r = g[["open", "high", "low", "close", "volume"]].resample(rule, origin="start").agg(agg)
        r = r.dropna(subset=["open"])
        out_frames.append(r)
    resampled = pd.concat(out_frames).sort_index()
    return _attach_local_columns(resampled)


def flag_corrupt_days(
    df: pd.DataFrame,
    *,
    max_daily_move: float = 0.35,
    roll_window: int = 21,
    max_local_dev: float = 0.5,
) -> list[object]:
    """Return trade dates whose bars look corrupted (wrong-symbol / mis-adjusted).

    Two complementary screens, both computed on the *daily* close series so they
    work identically for daily bars and for the daily rollup of intraday frames:

    - **Impossible jump:** a close-to-close move larger than ``max_daily_move``
      (35%). SPY's worst real single-day move in this history is ~-11% (COVID),
      so anything past 35% is a data artifact, not a market event.
    - **Local level spike:** a close deviating more than ``max_local_dev`` (50%)
      from a centered rolling-median of the close. The rolling median tracks the
      genuine multi-year trend, so this catches a localized ~$100 spike inside a
      ~$600 stretch without false-flagging the slow 2016->2026 drift that a
      global-median test would trip on.

    This is a whole-history data-cleaning pass, not a live signal -- strategies
    only ever see the cleaned frame, so no lookahead reaches them.
    """
    daily_close = df.groupby("date")["close"].last()
    dates = list(daily_close.index)

    # Screen 1: impossible close-to-close jumps.
    ret = daily_close.pct_change()
    jump_bad = {d for d, r in ret.items() if pd.notna(r) and abs(r) > max_daily_move}

    # Screen 2: local level spikes vs a centered rolling median.
    roll_med = daily_close.rolling(roll_window, center=True, min_periods=5).median()
    dev = (daily_close - roll_med).abs() / roll_med
    level_bad = {d for d, x in dev.items() if pd.notna(x) and x > max_local_dev}

    bad = jump_bad | level_bad
    return [d for d in dates if d in bad]


def load_clean_bars(
    cache_dir: Path,
    *,
    timeframe: str = "1Day",
    resample_rule: str | None = None,
    **kwargs: object,
) -> tuple[pd.DataFrame, list[object]]:
    """Load bars, optionally resample, and drop corrupt trade dates.

    Returns ``(clean_df, dropped_dates)``. Corruption is detected on the loaded
    (post-resample) frame, then any flagged trade date is removed whole so no
    partial session survives.
    """
    df = load_bars_df(cache_dir, timeframe=timeframe, **kwargs)  # type: ignore[arg-type]
    if resample_rule is not None:
        df = resample_session(df, resample_rule)
    bad = flag_corrupt_days(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()
    return df, bad


@dataclass(frozen=True, slots=True)
class SplitFrames:
    """Chronological train/test split of a bar frame (no shuffling, no leakage)."""

    train: pd.DataFrame
    test: pd.DataFrame
    split_date: object


def chronological_split(df: pd.DataFrame, *, train_frac: float = 0.7) -> SplitFrames:
    """Split bars into train/test by trade date (chronological, no overlap).

    Splitting on *dates* (not raw rows) means no session is cut across the
    boundary; the boundary date itself goes to the test set.
    """
    dates = sorted(set(df["date"]))
    if len(dates) < 2:
        msg = "need at least two trade dates to split"
        raise ValueError(msg)
    cut = int(len(dates) * train_frac)
    cut = max(1, min(cut, len(dates) - 1))
    split_date = dates[cut]
    train = df[df["date"] < split_date]
    test = df[df["date"] >= split_date]
    return SplitFrames(train=train, test=test, split_date=split_date)


def restrict_to_period(df: pd.DataFrame, *, start: object, end: object) -> pd.DataFrame:
    """Return rows whose trade date is within [start, end] inclusive (local dates)."""
    return df[(df["date"] >= start) & (df["date"] <= end)].copy()


__all__ = [
    "DEFAULT_SESSION_FOR_TIMEFRAME",
    "MARKET_TZ",
    "SplitFrames",
    "chronological_split",
    "flag_corrupt_days",
    "load_bars_df",
    "load_clean_bars",
    "resample_session",
    "restrict_to_period",
]
