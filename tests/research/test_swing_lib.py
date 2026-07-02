"""Tests for the reusable SPY swing / multi-timeframe helpers (research/lib).

These exercise the deterministic, reusable logic of the swing track on synthetic
in-memory frames — no network, no real cache:

- session-aware resampling (never spans the overnight gap; correct OHLC agg),
- multi-year corruption detection (catches spikes/impossible jumps, does NOT
  false-flag a legitimate long-term trend),
- chronological splitting and period restriction,
- the no-lookahead one-bar shift and the overnight-hold discipline,
- the swing backtest harness cost monotonicity, sizing guard, and the underwater
  duration helper.

``research/`` is not a uv-workspace member, so we add the repo root to sys.path.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from research.lib.swing_backtest import (  # noqa: E402
    run_swing_backtest,
    underwater_duration_days,
)
from research.lib.swing_data import (  # noqa: E402
    chronological_split,
    flag_corrupt_days,
    resample_session,
    restrict_to_period,
)
from research.lib.swing_strategies import (  # noqa: E402
    buy_and_hold,
    finalize_swing,
    overnight_hold,
    sma_trend,
)


# --- synthetic frame builders --------------------------------------------
def _daily_frame(closes: list[float], start: str = "2020-01-01") -> pd.DataFrame:
    """Daily OHLCV frame at midnight-ET (05:00 UTC), like cached SPY 1Day bars."""
    idx = pd.date_range(f"{start} 05:00:00", periods=len(closes), freq="1D", tz="UTC")
    close = pd.Series(closes, index=idx, dtype=float)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
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


def _intraday_frame(dates: list[str], bars_per_day: int = 6) -> pd.DataFrame:
    """Small multi-day intraday frame (bars_per_day 1-hour bars from 13:30 UTC)."""
    frames = []
    for d in dates:
        start = pd.Timestamp(f"{d} 13:30:00", tz="UTC")
        idx = pd.date_range(start, periods=bars_per_day, freq="1h", tz="UTC")
        frames.append(idx)
    idx = frames[0].append(frames[1:]) if len(frames) > 1 else frames[0]
    rng = np.random.default_rng(1)
    close = pd.Series(600 + rng.standard_normal(len(idx)).cumsum() * 0.1, index=idx)
    df = pd.DataFrame(
        {"open": close, "high": close + 0.2, "low": close - 0.2, "close": close, "volume": 500},
        index=idx,
    )
    local = df.index.tz_convert("America/New_York")
    df["local_ts"] = local
    df["date"] = local.date
    df["time"] = local.time
    return df


# --- resampling -----------------------------------------------------------
def test_resample_session_never_spans_overnight() -> None:
    df = _intraday_frame(["2024-03-04", "2024-03-05"], bars_per_day=6)
    out = resample_session(df, "3h")
    # Each 6-bar day splits into two 3h buckets => 2 buckets/day, never merging
    # the two calendar dates into one bar.
    counts = out.groupby("date").size()
    assert set(counts.index) == {date(2024, 3, 4), date(2024, 3, 5)}
    assert (counts == 2).all()


def test_resample_session_ohlc_aggregation() -> None:
    df = _intraday_frame(["2024-03-04"], bars_per_day=6)
    out = resample_session(df, "6h")  # whole day into one bar
    assert len(out) == 1
    row = out.iloc[0]
    assert row["open"] == pytest.approx(df["open"].iloc[0])
    assert row["close"] == pytest.approx(df["close"].iloc[-1])
    assert row["high"] == pytest.approx(df["high"].max())
    assert row["low"] == pytest.approx(df["low"].min())
    assert row["volume"] == pytest.approx(df["volume"].sum())


# --- corruption detection -------------------------------------------------
def test_flag_corrupt_days_catches_local_spike() -> None:
    closes = [600.0] * 20 + [100.0] + [600.0] * 20  # one implausible ~$100 day
    df = _daily_frame(closes)
    bad = flag_corrupt_days(df)
    assert len(bad) >= 1
    spike_date = df["date"].iloc[20]
    assert spike_date in set(bad)


def test_flag_corrupt_days_ignores_legitimate_trend() -> None:
    # A slow, monotonic 200 -> 700 climb (like SPY 2016->2026) must NOT be
    # flagged, even though early prices are <50% of the median.
    closes = list(np.linspace(200.0, 700.0, 260))
    df = _daily_frame(closes)
    assert flag_corrupt_days(df) == []


def test_flag_corrupt_days_catches_impossible_jump() -> None:
    closes = [600.0] * 10 + [900.0] + [900.0] * 10  # +50% one-day jump (impossible)
    df = _daily_frame(closes)
    assert len(flag_corrupt_days(df)) >= 1


# --- splitting / restriction ---------------------------------------------
def test_chronological_split_no_overlap() -> None:
    df = _daily_frame([600.0 + i for i in range(100)])
    split = chronological_split(df, train_frac=0.7)
    assert set(split.train["date"]).isdisjoint(set(split.test["date"]))
    assert max(split.train["date"]) < min(split.test["date"])
    assert split.split_date == min(split.test["date"])


def test_restrict_to_period_inclusive() -> None:
    df = _daily_frame([600.0] * 40, start="2024-01-01")
    lo, hi = df["date"].iloc[10], df["date"].iloc[20]
    out = restrict_to_period(df, start=lo, end=hi)
    assert out["date"].min() == lo
    assert out["date"].max() == hi


# --- signal discipline ----------------------------------------------------
def test_finalize_swing_shift_removes_same_bar_action() -> None:
    idx = pd.date_range("2024-01-01 05:00", periods=5, freq="1D", tz="UTC")
    entries = pd.Series([True, False, False, False, False], index=idx)
    exits = pd.Series(False, index=idx)
    sig = finalize_swing(entries, exits, shift=True)
    # The raw signal on bar 0 must execute on bar 1, never bar 0 (no lookahead).
    assert not bool(sig.entries.iloc[0])
    assert bool(sig.entries.iloc[1])


def test_buy_and_hold_single_entry_no_exit() -> None:
    df = _daily_frame([600.0 + i for i in range(30)])
    sig = buy_and_hold(df)
    assert int(sig.entries.sum()) == 1
    assert bool(sig.entries.iloc[0])
    assert int(sig.exits.sum()) == 0


def test_overnight_hold_enters_last_bar_exits_first_bar() -> None:
    df = _intraday_frame(["2024-03-04", "2024-03-05"], bars_per_day=6)
    sig = overnight_hold(df)
    # One entry (last bar) and one exit (first bar) per trade date; positions are
    # held across the overnight gap, never intraday.
    assert int(sig.entries.groupby(df["date"]).sum().max()) == 1
    assert int(sig.exits.groupby(df["date"]).sum().max()) == 1
    entry_times = df["time"][sig.entries]
    assert (entry_times == df["time"].max()).all()


def test_sma_trend_no_lookahead_and_boolean() -> None:
    df = _daily_frame(list(np.linspace(500, 700, 300)))
    sig = sma_trend(df, window=50)
    assert sig.entries.dtype == bool
    assert sig.exits.dtype == bool
    # First bar can never signal (needs the SMA warmup + the execution shift).
    assert not bool(sig.entries.iloc[0])


# --- backtest harness -----------------------------------------------------
def test_cost_monotonicity() -> None:
    # Net profit must not increase as commission rises (all else equal).
    df = _daily_frame(list(500 + np.sin(np.linspace(0, 20, 400)) * 20 + np.linspace(0, 60, 400)))
    sig = sma_trend(df, window=20)
    nets = []
    for comm in ("none", "tiered_mid", "fixed"):
        m = run_swing_backtest(
            df, sig, label="t", timeframe="1Day", commission_scenario=comm, slippage_scenario="none"
        )
        nets.append(m.net_profit)
    assert nets[0] >= nets[1] >= nets[2]


def test_impossible_size_rejected() -> None:
    # Reference price above the $2,000 cash balance => cannot buy one share.
    df = _daily_frame([5_000.0] * 30)
    sig = buy_and_hold(df)
    with pytest.raises(ValueError, match="impossible size"):
        run_swing_backtest(df, sig, label="t", timeframe="1Day")


def test_underwater_duration_zero_when_monotonic() -> None:
    idx = pd.date_range("2024-01-01", periods=10, freq="1D", tz="UTC")
    equity = pd.Series(np.arange(10.0) + 1.0, index=idx)  # strictly increasing
    assert underwater_duration_days(equity) == 0


def test_underwater_duration_measures_calendar_days() -> None:
    idx = pd.date_range("2024-01-01", periods=6, freq="1D", tz="UTC")
    equity = pd.Series([10.0, 9.0, 8.0, 9.5, 11.0, 12.0], index=idx)  # underwater bars 1-3
    # Peak at bar 0; underwater across bars 1,2,3 until a new high at bar 4.
    assert underwater_duration_days(equity) == 3
