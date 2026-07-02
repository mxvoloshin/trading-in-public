"""Shared data-access helpers for the SPY 5-minute intraday research track.

These wrap the existing ``trade_data`` store + ``trade_vectorbt`` adapter so
every research script loads bars the same way (same seam the backtest engine
uses) and gets an identical, session-aware OHLCV frame. Keeping this here (a)
avoids copy-pasting the load/convert dance into every script and (b) gives the
test suite one importable place to exercise the reusable logic.
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


def load_spy_5min(
    cache_dir: Path,
    *,
    symbol: str = "SPY",
    timeframe: str = "5Min",
    start: datetime | None = None,
    end: datetime | None = None,
) -> pd.DataFrame:
    """Load normalized SPY 5-minute bars into a tz-aware OHLCV DataFrame.

    Reads the same normalized JSONL cache the backtest engine reads (never
    Alpaca directly). Returns a UTC-indexed frame with lowercase OHLCV columns
    plus a ``local_ts`` (America/New_York), ``date`` (market-local trade date)
    and ``time`` (market-local time-of-day) helper columns that every
    market-structure and time-of-day analysis needs.
    """
    store = LocalMarketDataStore(cache_dir)
    instrument = Instrument.us_equity(symbol)
    session_config = get_market_session_config(instrument.market)

    # Default to a wide window; the store filters to whatever partitions exist.
    start = start or datetime(2000, 1, 1, tzinfo=UTC)
    end = end or datetime(2100, 1, 1, tzinfo=UTC)
    request = HistoricalBarsRequest(
        instrument=instrument,
        timeframe=timeframe,
        start_utc=start,
        end_utc=end,
    )
    bars = store.load_bars(request, session_config)
    if not bars:
        msg = f"no cached bars for {instrument.instrument_id} {timeframe}"
        raise ValueError(msg)

    df = to_ohlcv_dataframe(bars)
    # Attach market-local helper columns used pervasively downstream.
    local = df.index.tz_convert(MARKET_TZ)
    df = df.copy()
    df["local_ts"] = local
    df["date"] = local.date
    df["time"] = local.time
    return df


def flag_corrupt_days(df: pd.DataFrame, *, max_dev: float = 0.5) -> list[object]:
    """Return trade dates whose price level is implausibly far from the trend.

    Guards against corrupted cache segments (e.g. a wrong-symbol or mis-adjusted
    fetch) that would otherwise inject fake overnight jumps into every backtest.
    We compare each day's median close to the *global* median of daily medians;
    a day deviating by more than ``max_dev`` (50% by default) is flagged. The
    global median is robust because corrupt days are a small minority, and it
    avoids the baseline-contamination that a rolling window suffers at the edges
    of a corrupt run (which would false-flag the clean transition days). This is
    a data-cleaning pass over the whole history, not a live signal — no lookahead
    reaches the strategies, which only ever see the cleaned frame.

    Assumption: the instrument's genuine price does not swing more than ``max_dev``
    from its median across the loaded window (true for this ~1yr SPY sample,
    range 616-757 vs median 678). Widen the window or revisit this if a
    multi-year sample with a larger real trend is loaded.
    """
    daily_med = df.groupby("date")["close"].median()
    baseline = daily_med.median()
    dev = (daily_med - baseline).abs() / baseline
    return [d for d, bad in (dev > max_dev).items() if bool(bad)]


def load_clean_spy_5min(cache_dir: Path, **kwargs: object) -> tuple[pd.DataFrame, list[object]]:
    """Load SPY bars and drop corrupted trade dates. Returns (clean_df, dropped_dates)."""
    df = load_spy_5min(cache_dir, **kwargs)  # type: ignore[arg-type]
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

    Splitting on *dates* (not raw bar rows) guarantees no single session is cut
    in half across the boundary, which would corrupt intraday statistics. The
    boundary date itself goes to the test set.
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


__all__ = [
    "MARKET_TZ",
    "SplitFrames",
    "chronological_split",
    "flag_corrupt_days",
    "load_clean_spy_5min",
    "load_spy_5min",
]
