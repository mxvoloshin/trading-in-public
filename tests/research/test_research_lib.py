"""Tests for the reusable SPY intraday research helpers (research/lib).

These exercise the deterministic, reusable logic — corrupt-day detection,
chronological splitting, the no-lookahead / EOD-flat signal discipline, and the
cost-model mapping — on synthetic in-memory frames. No network, no real cache.

``research/`` is not part of the uv workspace, so we add the repo root to
``sys.path`` before importing.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from research.lib.backtest import run_intraday_backtest  # noqa: E402
from research.lib.data_access import chronological_split, flag_corrupt_days  # noqa: E402
from research.lib.strategies import (  # noqa: E402
    FLATTEN_TIME,
    LAST_ENTRY_TIME,
    buy_open_sell_close_signals,
    finalize_intraday,
)

BARS_PER_DAY = 78


def _session_index(date: str) -> pd.DatetimeIndex:
    """78 five-minute UTC bars for a single 9:30->16:00 ET regular session."""
    # 9:30 ET == 13:30 UTC (EDT). Good enough for deterministic test bars.
    start = pd.Timestamp(f"{date} 13:30:00", tz="UTC")
    return pd.date_range(start, periods=BARS_PER_DAY, freq="5min", tz="UTC")


def _make_frame(dates: list[str], base_price: float = 600.0) -> pd.DataFrame:
    """Build a multi-day intraday OHLCV frame with the helper columns."""
    idxs = [_session_index(d) for d in dates]
    idx = idxs[0].append(idxs[1:]) if len(idxs) > 1 else idxs[0]
    rng = np.random.default_rng(0)
    close = pd.Series(base_price + rng.standard_normal(len(idx)).cumsum() * 0.1, index=idx)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 0.2,
            "low": close - 0.2,
            "close": close,
            "volume": 1_000,
        },
        index=idx,
    )
    local = df.index.tz_convert("America/New_York")
    df["local_ts"] = local
    df["date"] = local.date
    df["time"] = local.time
    return df


def test_flag_corrupt_days_detects_low_price_segment() -> None:
    df = _make_frame(["2025-07-01", "2025-07-02", "2025-07-03"], base_price=600.0)
    # Corrupt the middle day to ~1/6 of normal price (a wrong-symbol segment).
    mask = df["date"] == pd.Timestamp("2025-07-02").date()
    df.loc[mask, ["open", "high", "low", "close"]] /= 6.0
    corrupt = flag_corrupt_days(df)
    assert pd.Timestamp("2025-07-02").date() in corrupt
    assert pd.Timestamp("2025-07-01").date() not in corrupt
    assert pd.Timestamp("2025-07-03").date() not in corrupt


def test_flag_corrupt_days_clean_data_flags_nothing() -> None:
    df = _make_frame(["2025-07-01", "2025-07-02", "2025-07-03"])
    assert flag_corrupt_days(df) == []


def test_chronological_split_no_overlap() -> None:
    df = _make_frame([f"2025-07-{d:02d}" for d in range(1, 11)])
    split = chronological_split(df, train_frac=0.7)
    train_dates = set(split.train["date"])
    test_dates = set(split.test["date"])
    assert train_dates.isdisjoint(test_dates)
    assert max(train_dates) < min(test_dates)  # strictly chronological
    assert len(train_dates) + len(test_dates) == 10


def test_finalize_intraday_shifts_and_flattens() -> None:
    df = _make_frame(["2025-07-01"])
    # Raw entry on bar 0 (9:30) — should shift to bar 1 (no same-bar fill).
    entries = pd.Series(False, index=df.index)
    entries.iloc[0] = True
    exits = pd.Series(False, index=df.index)
    sig = finalize_intraday(entries, exits, df)
    assert not bool(sig.entries.iloc[0])  # shifted away from signal bar
    assert bool(sig.entries.iloc[1])  # executes next bar

    # No entries at/after the last-entry cutoff.
    times = df["time"]
    late = sig.entries[times >= LAST_ENTRY_TIME]
    assert not late.any()

    # Forced exit on every bar at/after flatten time (guarantees flat by EOD).
    eod = sig.exits[times >= FLATTEN_TIME]
    assert eod.all()


def test_finalize_intraday_no_overnight_carry() -> None:
    df = _make_frame(["2025-07-01", "2025-07-02"])
    # Entry on the very last bar of day 1 would, if shifted naively, land on
    # day 2's first bar. The same-day groupby shift must prevent that.
    entries = pd.Series(False, index=df.index)
    entries.iloc[BARS_PER_DAY - 1] = True  # last bar of day 1
    exits = pd.Series(False, index=df.index)
    sig = finalize_intraday(entries, exits, df)
    assert not bool(sig.entries.iloc[BARS_PER_DAY])  # no carry into day 2 open


def test_run_intraday_backtest_cost_monotonicity() -> None:
    df = _make_frame([f"2025-07-{d:02d}" for d in range(1, 11)])
    sig = buy_open_sell_close_signals(df)
    cheap = run_intraday_backtest(
        df, sig, label="t", commission_scenario="none", slippage_scenario="none"
    )
    dear = run_intraday_backtest(
        df, sig, label="t", commission_scenario="fixed", slippage_scenario="stress"
    )
    # More cost can only reduce net return.
    assert dear.total_return_pct <= cheap.total_return_pct
    assert cheap.total_trades == dear.total_trades
    assert cheap.max_shares >= 1


def test_run_intraday_backtest_rejects_impossible_size() -> None:
    df = _make_frame(["2025-07-01"], base_price=600.0)
    sig = buy_open_sell_close_signals(df)
    # $10 account cannot buy a single ~$600 share even with 2x buying power.
    with pytest.raises(ValueError, match="impossible position size"):
        run_intraday_backtest(df, sig, label="t", init_cash=10.0)
