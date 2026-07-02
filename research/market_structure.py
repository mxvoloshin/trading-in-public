"""Market-structure analysis of clean SPY 5-minute bars.

Characterizes the raw statistical behavior of the session *before* any strategy
is proposed, so hypotheses are data-driven rather than guessed. Computes:

- 5-minute / overnight / intraday return distributions
- time-of-day profiles: mean return, volatility, volume, high-low range
- opening-range and opening-gap behavior
- 5-minute return autocorrelation (momentum vs mean-reversion)
- day-of-week effects

Writes ``research/results/market_structure.json`` and PNG charts under
``research/charts/``.

Run:
    uv run python research/market_structure.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # headless / no display
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.lib.data_access import load_clean_spy_5min  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".data"
RESULTS_DIR = REPO_ROOT / "research" / "results"
CHARTS_DIR = REPO_ROOT / "research" / "charts"

BARS_PER_DAY = 78


def _pct(series: pd.Series, q: float) -> float:
    return float(series.quantile(q))


def analyze(df: pd.DataFrame) -> dict[str, object]:
    """Compute market-structure statistics from clean bars."""
    out: dict[str, object] = {}

    # --- Intraday 5-min returns (within-session only) ---------------------
    # Compute per-day so we never span the overnight gap.
    intraday_ret: list[pd.Series] = []
    overnight_ret: list[float] = []
    prev_close: float | None = None
    for _date, g in df.groupby("date"):
        r = g["close"].pct_change().dropna()
        intraday_ret.append(r)
        first_open = float(g["open"].iloc[0])
        if prev_close is not None:
            overnight_ret.append(first_open / prev_close - 1.0)
        prev_close = float(g["close"].iloc[-1])
    intr = pd.concat(intraday_ret)

    out["intraday_5min_return"] = {
        "mean_bps": float(intr.mean() * 1e4),
        "std_bps": float(intr.std() * 1e4),
        "p01_bps": _pct(intr, 0.01) * 1e4,
        "p99_bps": _pct(intr, 0.99) * 1e4,
        "skew": float(intr.skew()),
        "kurtosis": float(intr.kurtosis()),
        "annualized_vol_pct": float(intr.std() * np.sqrt(BARS_PER_DAY * 252) * 100),
    }

    on = pd.Series(overnight_ret)
    out["overnight_return"] = {
        "mean_bps": float(on.mean() * 1e4),
        "std_bps": float(on.std() * 1e4),
        "share_of_daily_var_pct": float(
            on.var() / (on.var() + intr.groupby(df["date"]).sum().var()) * 100
        ),
    }

    # --- Daily (close-to-close) returns -----------------------------------
    daily_close = df.groupby("date")["close"].last()
    daily_ret = daily_close.pct_change().dropna()
    out["daily_close_to_close"] = {
        "mean_pct": float(daily_ret.mean() * 100),
        "std_pct": float(daily_ret.std() * 100),
        "annualized_return_pct": float(daily_ret.mean() * 252 * 100),
        "annualized_vol_pct": float(daily_ret.std() * np.sqrt(252) * 100),
        "sharpe_naive": float(daily_ret.mean() / daily_ret.std() * np.sqrt(252)),
        "pct_up_days": float((daily_ret > 0).mean() * 100),
    }

    # Open-to-close (intraday-only) daily return — this is what a flat-by-EOD
    # strategy actually competes against.
    daily_open = df.groupby("date")["open"].first()
    o2c = (daily_close / daily_open - 1.0).dropna()
    out["daily_open_to_close"] = {
        "mean_pct": float(o2c.mean() * 100),
        "std_pct": float(o2c.std() * 100),
        "annualized_return_pct": float(o2c.mean() * 252 * 100),
        "pct_up_days": float((o2c > 0).mean() * 100),
    }

    # --- Time-of-day profiles ---------------------------------------------
    df = df.copy()
    df["ret"] = df.groupby("date")["close"].pct_change()
    df["range_bps"] = (df["high"] - df["low"]) / df["close"] * 1e4
    tod = df.groupby("time").agg(
        mean_ret_bps=("ret", lambda s: float(s.mean() * 1e4)),
        std_ret_bps=("ret", lambda s: float(s.std() * 1e4)),
        mean_range_bps=("range_bps", "mean"),
        mean_volume=("volume", "mean"),
        n=("ret", "count"),
    )
    out["time_of_day"] = {
        str(t): {
            "mean_ret_bps": float(row.mean_ret_bps),
            "std_ret_bps": float(row.std_ret_bps),
            "mean_range_bps": float(row.mean_range_bps),
            "mean_volume": float(row.mean_volume),
        }
        for t, row in tod.iterrows()
    }

    # --- Opening range & gap behavior -------------------------------------
    # First 30 min (6 bars) range vs rest-of-day continuation.
    or_stats: list[dict[str, float]] = []
    for _date, g in df.groupby("date"):
        if len(g) < BARS_PER_DAY:
            continue
        or_bars = g.iloc[:6]
        rest = g.iloc[6:]
        or_high = float(or_bars["high"].max())
        or_low = float(or_bars["low"].min())
        or_range = or_high - or_low
        day_open = float(g["open"].iloc[0])
        day_close = float(g["close"].iloc[-1])
        # Did price break the OR high/low after the first 30 min, and did it
        # close the day beyond that level (breakout continuation)?
        broke_up = bool((rest["high"] > or_high).any())
        broke_dn = bool((rest["low"] < or_low).any())
        or_stats.append(
            {
                "or_range_bps": or_range / day_open * 1e4,
                "broke_up": float(broke_up),
                "broke_dn": float(broke_dn),
                "close_above_orhigh": float(day_close > or_high),
                "close_below_orlow": float(day_close < or_low),
                "o2c_bps": (day_close / day_open - 1.0) * 1e4,
            }
        )
    ors = pd.DataFrame(or_stats)
    out["opening_range_30min"] = {
        "mean_or_range_bps": float(ors["or_range_bps"].mean()),
        "pct_days_break_up": float(ors["broke_up"].mean() * 100),
        "pct_days_break_dn": float(ors["broke_dn"].mean() * 100),
        "pct_days_close_above_orhigh": float(ors["close_above_orhigh"].mean() * 100),
        "pct_days_close_below_orlow": float(ors["close_below_orlow"].mean() * 100),
        # Of days that broke up, how often did they close above OR high?
        "up_break_continuation_pct": float(
            ors.loc[ors["broke_up"] == 1, "close_above_orhigh"].mean() * 100
        ),
        "dn_break_continuation_pct": float(
            ors.loc[ors["broke_dn"] == 1, "close_below_orlow"].mean() * 100
        ),
    }

    # --- Autocorrelation of 5-min returns (momentum vs mean reversion) ----
    # Computed within-day and averaged, so overnight gaps never enter.
    acf: dict[int, list[float]] = {lag: [] for lag in (1, 2, 3, 6, 12)}
    for _date, g in df.groupby("date"):
        r = g["close"].pct_change().dropna()
        for lag in acf:
            if len(r) > lag + 5:
                acf[lag].append(float(r.autocorr(lag)))
    out["return_autocorrelation"] = {
        f"lag_{lag}": float(np.nanmean(vals)) for lag, vals in acf.items()
    }

    # --- Day-of-week effect (open-to-close) -------------------------------
    o2c_by_date = (daily_close / daily_open - 1.0).dropna()
    dow = pd.Series(
        o2c_by_date.values,
        index=pd.to_datetime(pd.Index(o2c_by_date.index)).dayofweek,
    )
    dow_names = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri"}
    out["day_of_week_o2c_bps"] = {
        dow_names[d]: float(dow[dow.index == d].mean() * 1e4)
        for d in sorted(set(dow.index))
        if d in dow_names
    }

    return out, tod, ors  # type: ignore[return-value]


def make_charts(tod: pd.DataFrame, ors: pd.DataFrame) -> list[str]:
    """Render time-of-day and opening-range charts. Returns saved paths."""
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    times = [str(t)[:5] for t in tod.index]

    # Time-of-day: volatility, range, volume.
    fig, axes = plt.subplots(3, 1, figsize=(11, 10), sharex=True)
    axes[0].plot(times, tod["std_ret_bps"], color="tab:blue")
    axes[0].set_ylabel("5-min return std (bps)")
    axes[0].set_title("SPY intraday volatility by time of day (ET)")
    axes[1].plot(times, tod["mean_range_bps"], color="tab:orange")
    axes[1].set_ylabel("mean high-low range (bps)")
    axes[2].bar(times, tod["mean_volume"], color="tab:green")
    axes[2].set_ylabel("mean volume")
    axes[2].set_xlabel("time of day (ET)")
    for ax in axes:
        ax.grid(True, alpha=0.3)
    step = max(1, len(times) // 13)
    axes[2].set_xticks(range(0, len(times), step))
    axes[2].set_xticklabels(times[::step], rotation=45, ha="right")
    fig.tight_layout()
    p1 = CHARTS_DIR / "time_of_day_profile.png"
    fig.savefig(p1, dpi=110)
    plt.close(fig)
    paths.append(str(p1))

    # Mean return by time of day (directionality).
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(times, tod["mean_ret_bps"], color="tab:purple")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("mean 5-min return (bps)")
    ax.set_title("SPY mean return by time of day (ET) — directional drift")
    ax.set_xticks(range(0, len(times), step))
    ax.set_xticklabels(times[::step], rotation=45, ha="right")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    p2 = CHARTS_DIR / "time_of_day_mean_return.png"
    fig.savefig(p2, dpi=110)
    plt.close(fig)
    paths.append(str(p2))

    return paths


def main() -> None:
    df, dropped = load_clean_spy_5min(CACHE_DIR)
    result, tod, ors = analyze(df)  # type: ignore[misc]
    result["_meta"] = {
        "clean_trade_days": int(df["date"].nunique()),
        "dropped_corrupt_days": [str(d) for d in dropped],
        "start": str(df["date"].min()),
        "end": str(df["date"].max()),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "market_structure.json"
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    charts = make_charts(tod, ors)

    print("=== SPY 5-min Market Structure (clean data) ===")
    summary = {k: v for k, v in result.items() if not k.startswith("time_of_day")}
    print(json.dumps(summary, indent=2)[:3000])
    print("\ncharts:", charts)
    print("wrote", out)


if __name__ == "__main__":
    main()
