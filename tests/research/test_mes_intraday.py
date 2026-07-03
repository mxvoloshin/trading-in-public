"""Tests for the MES intraday futures research harness (research/mes_intraday).

These exercise the deterministic, reusable logic on synthetic in-memory frames:
the futures dollar math ($5/point), long *and* short accounting, cost monotonicity,
the intrabar stop/target, the flat-by-EOD / no-lookahead discipline, session VWAP
reset, and the robust (local-trend) corrupt-day filter. No network, no real cache.

``research/`` is not part of the uv workspace, so we add the repo root to
``sys.path`` before importing.
"""

from __future__ import annotations

import sys
from datetime import time as dt_time
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from research.mes_intraday.exits import (  # noqa: E402
    ExitPolicy,
    atr_series,
    simulate_with_exits,
)
from research.mes_intraday.lib import (  # noqa: E402
    POINT_VALUE,
    SPY_TO_INDEX,
    LSSignals,
    compute_metrics,
    finalize_ls,
    flag_corrupt_days_local,
    session_vwap,
    simulate_mes,
)
from research.mes_intraday.novel import (  # noqa: E402
    _day_features,  # pyright: ignore[reportPrivateUsage]
    gap_and_go,
)

BARS_PER_DAY = 78


def _session_index(date: str) -> pd.DatetimeIndex:
    """78 five-minute bars for one 9:30->15:55 ET session, returned as a UTC index.

    Built in America/New_York and converted to UTC so the market-local time-of-day
    is correct in both EST and EDT (the flatten logic keys off 15:55 ET, which a
    naive fixed-UTC start would miss in winter).
    """
    start = pd.Timestamp(f"{date} 09:30:00", tz="America/New_York")
    local = pd.date_range(start, periods=BARS_PER_DAY, freq="5min", tz="America/New_York")
    return local.tz_convert("UTC")


def _make_frame(dates: list[str], base_price: float = 600.0) -> pd.DataFrame:
    """Build a multi-day intraday OHLCV frame with the helper columns."""
    idxs = [_session_index(d) for d in dates]
    idx = idxs[0].append(idxs[1:]) if len(idxs) > 1 else idxs[0]
    rng = np.random.default_rng(0)
    close = pd.Series(base_price + rng.standard_normal(len(idx)).cumsum() * 0.1, index=idx)
    df = pd.DataFrame(
        {"open": close, "high": close + 0.2, "low": close - 0.2, "close": close, "volume": 1_000},
        index=idx,
    )
    local = df.index.tz_convert("America/New_York")
    df["local_ts"] = local
    df["date"] = local.date
    df["time"] = local.time
    return df


def _flat(index: pd.Index) -> pd.Series:
    return pd.Series(False, index=index)


def test_mes_long_pnl_is_five_dollars_per_index_point() -> None:
    """A clean long trade must earn $5 per index point per contract (no costs)."""
    df = _make_frame(["2024-01-02"])
    # Enter on bar 1 (fills at bar 1 close), exit on bar 3 (fills at bar 3 close).
    entry_long = _flat(df.index).copy()
    exit_long = _flat(df.index).copy()
    entry_long.iloc[1] = True
    exit_long.iloc[3] = True
    sig = LSSignals(entry_long, exit_long, _flat(df.index), _flat(df.index))
    trades = simulate_mes(
        df, sig, contracts=1, commission_scenario="none", slippage_scenario="none"
    )
    assert len(trades) == 1
    t = trades[0]
    entry_pts = df["close"].iloc[1] * SPY_TO_INDEX
    exit_pts = df["close"].iloc[3] * SPY_TO_INDEX
    expected = (exit_pts - entry_pts) * POINT_VALUE
    assert t.direction == 1
    assert abs(t.pnl - expected) < 1e-6


def test_mes_short_profits_when_price_falls() -> None:
    """A short must profit when the index falls between entry and exit fills."""
    df = _make_frame(["2024-01-02"])
    # Force a clean downtrend so a short is profitable.
    falling = pd.Series(np.linspace(600.0, 590.0, len(df)), index=df.index)
    df = df.assign(open=falling, high=falling + 0.1, low=falling - 0.1, close=falling)
    entry_short = _flat(df.index).copy()
    exit_short = _flat(df.index).copy()
    entry_short.iloc[1] = True
    exit_short.iloc[10] = True
    sig = LSSignals(_flat(df.index), _flat(df.index), entry_short, exit_short)
    trades = simulate_mes(
        df, sig, contracts=1, commission_scenario="none", slippage_scenario="none"
    )
    assert len(trades) == 1
    assert trades[0].direction == -1
    assert trades[0].pnl > 0  # falling market, short wins


def test_costs_are_monotonic() -> None:
    """More commission and more slippage can only reduce a trade's P&L."""
    df = _make_frame(["2024-01-02"])
    rising = pd.Series(np.linspace(600.0, 610.0, len(df)), index=df.index)
    df = df.assign(open=rising, high=rising + 0.1, low=rising - 0.1, close=rising)
    entry_long = _flat(df.index).copy()
    exit_long = _flat(df.index).copy()
    entry_long.iloc[1] = True
    exit_long.iloc[20] = True
    sig = LSSignals(entry_long, exit_long, _flat(df.index), _flat(df.index))

    def pnl(comm: str, slip: str) -> float:
        return simulate_mes(df, sig, commission_scenario=comm, slippage_scenario=slip)[0].pnl

    assert pnl("none", "none") > pnl("mid", "none") > pnl("stress", "none")
    assert pnl("mid", "none") > pnl("mid", "one") > pnl("mid", "stress")


def test_stop_caps_the_loss() -> None:
    """With a stop, a losing long must exit near the stop, not run to a bigger loss."""
    df = _make_frame(["2024-01-02"])
    # Gradual decline after entry: the stop should exit early and high, while the
    # baseline (exit at the close) rides the position all the way down.
    prices = pd.Series(600.0, index=df.index)
    prices.iloc[2:] = np.linspace(597.0, 588.0, len(df) - 2)
    df = df.assign(open=prices, high=prices + 0.1, low=prices - 0.1, close=prices)
    entry_long = _flat(df.index).copy()
    entry_long.iloc[1] = True
    exit_long = _flat(df.index).copy()
    exit_long.iloc[-1] = True  # baseline exit at the last bar (no risk control)
    sig = LSSignals(entry_long, exit_long, _flat(df.index), _flat(df.index))

    no_stop = simulate_mes(df, sig, commission_scenario="none", slippage_scenario="none")
    with_stop = simulate_mes(
        df, sig, commission_scenario="none", slippage_scenario="none", stop_frac=0.003
    )
    assert with_stop[0].pnl > no_stop[0].pnl  # stop cut the loss short


def test_no_overnight_carry() -> None:
    """finalize_ls forces flat at EOD: no trade may span two trade dates."""
    df = _make_frame(["2024-01-02", "2024-01-03"])
    # Persistent long entry every bar; only the EOD flatten should close it.
    entry_long = pd.Series(True, index=df.index)
    sig = finalize_ls(entry_long, _flat(df.index), _flat(df.index), _flat(df.index), df)
    trades = simulate_mes(df, sig, commission_scenario="none", slippage_scenario="none")
    assert trades, "expected at least one trade"
    for t in trades:
        entry_date = t.entry_ts.tz_convert("America/New_York").date()
        exit_date = t.exit_ts.tz_convert("America/New_York").date()
        assert entry_date == exit_date, "position carried overnight"


def test_finalize_blocks_late_entries_and_shifts() -> None:
    """Entries after the last-entry time are dropped; kept entries are shifted +1 bar."""
    df = _make_frame(["2024-01-02"])
    raw = _flat(df.index).copy()
    raw.iloc[5] = True  # early, should survive (shifted to bar 6)
    late_mask = df["time"] >= dt_time(15, 45)
    raw[late_mask] = True  # late entries must be removed
    sig = finalize_ls(raw, _flat(df.index), _flat(df.index), _flat(df.index), df)
    assert not sig.entry_long[late_mask].any()
    assert bool(sig.entry_long.iloc[6])  # bar 5 signal executes on bar 6
    assert not bool(sig.entry_long.iloc[5])


def test_session_vwap_resets_each_day() -> None:
    """The first bar of each day has VWAP == that bar's typical price (fresh reset)."""
    df = _make_frame(["2024-01-02", "2024-01-03"])
    vwap = session_vwap(df)
    for _d, g in df.groupby("date"):
        first = g.index[0]
        typical = (df["high"][first] + df["low"][first] + df["close"][first]) / 3.0
        assert abs(vwap[first] - typical) < 1e-6


def test_flag_corrupt_days_local_catches_wrong_symbol_segment() -> None:
    """A ~$100 segment surrounded by a ~$600 trend is flagged; clean days are not.

    The corrupt day sits in the middle with clean days on both sides so the
    trailing/leading reference window is dominated by clean prices (the first day
    of a sample uses a leading window, which must stay clean to avoid a false flag).
    """
    dates = [f"2024-01-{d:02d}" for d in (2, 3, 4, 5, 8, 9)]
    df = _make_frame(dates, base_price=600.0)
    bad_day = df["date"].unique()[3]
    mask = df["date"] == bad_day
    df.loc[mask, ["open", "high", "low", "close"]] = 100.0
    flagged = flag_corrupt_days_local(df, window=21, max_dev=0.35)
    assert bad_day in flagged
    assert len(flagged) == 1


def test_flag_corrupt_days_local_allows_real_trend() -> None:
    """A genuine gradual drift (no single day >35% off the local trend) is not flagged."""
    dates = [f"2024-01-{d:02d}" for d in range(2, 20)]
    df = _make_frame(dates, base_price=600.0)
    # Gentle 20% drift across ~18 days — like a normal bull leg, well under the
    # 35% single-day deviation the corrupt filter looks for.
    levels = np.linspace(600.0, 720.0, len(dates))
    for d, lvl in zip(df["date"].unique(), levels, strict=True):
        m = df["date"] == d
        df.loc[m, ["open", "high", "low", "close"]] = lvl
    assert flag_corrupt_days_local(df, window=21, max_dev=0.35) == []


def test_day_features_overnight_gap() -> None:
    """The per-day feature frame computes the overnight gap = day_open/prev_close - 1."""
    df = _make_frame(["2024-01-02", "2024-01-03"])
    # Day 1 flat at 600 (so prev_close = 600); day 2 opens at 606 (+1% gap).
    d1, d2 = df["date"].unique()
    df.loc[df["date"] == d1, ["open", "high", "low", "close"]] = 600.0
    df.loc[df["date"] == d2, ["open", "high", "low", "close"]] = 606.0
    feats = _day_features(df)
    assert abs(feats.loc[d2, "prev_close"] - 600.0) < 1e-9
    assert abs(feats.loc[d2, "gap"] - 0.01) < 1e-9


def test_gap_and_go_is_long_on_confirmed_gap_up_no_lookahead() -> None:
    """A gap-up day whose first bar follows through yields a *long*, entered after the open."""
    df = _make_frame(["2024-01-02", "2024-01-03"])
    d1, d2 = df["date"].unique()
    df.loc[df["date"] == d1, ["open", "high", "low", "close"]] = 600.0
    # Day 2 gaps up to 606 and the first bar closes above its open (follow-through),
    # then drifts higher — a textbook gap-and-go long setup.
    day2 = df.index[df["date"] == d2]
    ramp = np.linspace(606.0, 612.0, len(day2))
    df.loc[day2, "open"] = ramp
    df.loc[day2, "close"] = ramp + 0.3  # each bar closes above its open
    df.loc[day2, "high"] = ramp + 0.5
    df.loc[day2, "low"] = ramp - 0.2
    sig = gap_and_go(df, gap_thr=0.0015)
    day2_longs = sig.entry_long[df["date"] == d2]
    assert day2_longs.any(), "expected a long entry on the confirmed gap-up day"
    assert not sig.entry_short[df["date"] == d2].any(), "must not short a gap-up-and-go day"
    # No lookahead: nothing fires on the very first bar of the day (entries execute later).
    assert not bool(day2_longs.iloc[0])


def test_atr_series_is_positive_and_tracks_range() -> None:
    """ATR is positive and scales with bar range (a wider-range frame has larger ATR)."""
    df = _make_frame(["2024-01-02"])
    narrow = df.assign(high=df["close"] + 0.1, low=df["close"] - 0.1)
    wide = df.assign(high=df["close"] + 1.0, low=df["close"] - 1.0)
    a_narrow = atr_series(narrow, period=14).iloc[20:].mean()
    a_wide = atr_series(wide, period=14).iloc[20:].mean()
    assert a_narrow > 0
    assert a_wide > a_narrow


def test_time_exit_closes_position_at_configured_time() -> None:
    """A time-of-day exit flattens the position at/after the configured local time."""
    df = _make_frame(["2024-01-02"])
    entry_long = _flat(df.index).copy()
    entry_long.iloc[1] = True  # enter early in the day
    policy = ExitPolicy(label="t", time_exit=(12, 0))  # exit at noon ET
    trades = simulate_with_exits(
        df,
        entry_long,
        _flat(df.index),
        policy,
        commission_scenario="none",
        slippage_scenario="none",
    )
    assert len(trades) == 1
    exit_local = trades[0].exit_ts.tz_convert("America/New_York")
    # Exit must land at 12:00 (not the 15:55 EOD backstop).
    assert (exit_local.hour, exit_local.minute) == (12, 0)


def test_trailing_stop_locks_in_profit() -> None:
    """A ratcheting trail exits above entry once price runs up then pulls back."""
    df = _make_frame(["2024-01-02"])
    # Rise from 600 to 612, then fall back to 606 — a trail should exit in profit.
    up = np.linspace(600.0, 612.0, 40)
    down = np.linspace(612.0, 606.0, len(df) - 40)
    prices = pd.Series(np.concatenate([up, down]), index=df.index)
    df = df.assign(open=prices, high=prices + 0.1, low=prices - 0.1, close=prices)
    entry_long = _flat(df.index).copy()
    entry_long.iloc[1] = True
    policy = ExitPolicy(label="t", stop_frac=0.02, trail_frac=0.005)  # 0.5% trail
    trades = simulate_with_exits(
        df,
        entry_long,
        _flat(df.index),
        policy,
        commission_scenario="none",
        slippage_scenario="none",
    )
    assert len(trades) == 1
    # Exited on the pullback, above entry (the trail banked profit), not at EOD 606.
    assert trades[0].pnl > 0
    assert trades[0].exit_index > trades[0].entry_index


def test_metrics_flag_blowup_on_catastrophic_day() -> None:
    """A single day loss exceeding the margin buffer must set would_blow_up."""
    df = _make_frame(["2024-01-02"])
    crash = pd.Series(600.0, index=df.index)
    crash.iloc[2:] = 570.0  # -5% => ~150 index pts => $750/contract loss on a $2k acct
    df = df.assign(open=crash, high=crash + 0.1, low=crash - 0.1, close=crash)
    entry_long = _flat(df.index).copy()
    entry_long.iloc[1] = True
    exit_long = _flat(df.index).copy()
    exit_long.iloc[-1] = True  # hold the crash to the close (no stop)
    sig = LSSignals(entry_long, exit_long, _flat(df.index), _flat(df.index))
    trades = simulate_mes(df, sig, commission_scenario="none", slippage_scenario="none")
    m = compute_metrics(
        df, trades, label="t", contracts=1, commission_scenario="none", slippage_scenario="none"
    )
    assert len(trades) == 1
    assert m.would_blow_up is True
