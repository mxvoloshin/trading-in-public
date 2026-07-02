"""Convert provider-neutral ``Bar`` records into VectorBT-friendly DataFrames.

VectorBT (and pandas/NumPy generally) wants a single ``DataFrame`` with standard
OHLCV column names and a timezone-aware ``DatetimeIndex``. The rest of this repo
stores bars as provider-neutral ``Bar`` dataclasses in daily JSONL partitions;
this adapter is the one-way bridge from that representation into the numerical
world. It lives in ``trade_vectorbt`` (not ``trade_data``) so pandas/NumPy stay
isolated from the pure-stdlib data package.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd
from trade_data import Bar


def to_ohlcv_dataframe(bars: Sequence[Bar]) -> pd.DataFrame:
    """Build a tz-aware UTC OHLCV ``DataFrame`` from ``Bar`` records.

    The returned frame has columns ``open, high, low, close, volume`` (lowercase,
    as VectorBT's accessors expect) and a UTC ``DatetimeIndex`` named
    ``timestamp_utc``. Bars are sorted by timestamp and de-duplicated on it, so
    overlapping daily partitions merge cleanly when several days are loaded
    together.
    """
    if not bars:
        # Return an empty frame with the right columns/index name so downstream
        # vectorbt calls fail loudly on length rather than on shape.
        return pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []},
            index=pd.DatetimeIndex([], name="timestamp_utc", tz="UTC"),
        )

    # Build from records so dtypes are numeric (prices as float, volume as int).
    records = [
        {
            "timestamp_utc": bar.timestamp_utc,
            "open": float(bar.open),
            "high": float(bar.high),
            "low": float(bar.low),
            "close": float(bar.close),
            "volume": int(bar.volume),
        }
        for bar in bars
    ]
    df = pd.DataFrame.from_records(records, index="timestamp_utc")
    df.index = pd.DatetimeIndex(df.index, name="timestamp_utc", tz="UTC")
    # De-duplicate and order: overlapping daily partitions can repeat a bar at a
    # boundary when a refetch overlaps the prior fetch. Keep the last seen value.
    return df.sort_index().loc[~df.index.duplicated(keep="last")]


__all__ = ["to_ohlcv_dataframe"]
