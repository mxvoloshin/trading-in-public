"""Multi-timeframe market-structure analysis for the SPY swing research track.

Characterizes SPY's behavior *before* proposing strategies, so hypotheses are
data-driven. Unlike the intraday study (one 5-minute window), this looks across
timeframes and regimes:

- daily return / volatility stats over the **full 2016->2026 decade** and the
  **2025->2026 focus window** (so we can separate a robust edge from a bull-only
  artifact),
- overnight vs intraday return decomposition (does the drift still live
  overnight on this wider sample?),
- trend vs mean-reversion signature (daily/weekly autocorrelation and the
  variance ratio),
- N-day holding-period forward-return distributions (is there drift to harvest
  by holding longer?),
- buy & hold drawdown profile per regime, and the Reg-T 2x margin-call threshold.

Writes ``research/results/swing_market_structure.json`` plus charts under
``research/charts/``.

Run:
    uv run python research/swing_market_structure.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.lib.swing_data import (  # noqa: E402
    load_clean_bars,
    restrict_to_period,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".data"
RESULTS_DIR = REPO_ROOT / "research" / "results"
CHARTS_DIR = REPO_ROOT / "research" / "charts"

TRADING_DAYS = 252
FOCUS_START = date(2025, 1, 1)
FOCUS_END = date(2026, 12, 31)


def _daily_close(df: pd.DataFrame) -> pd.Series:
    """One close per trade date, indexed by date (works for any timeframe)."""
    return df.groupby("date")["close"].last()


def _return_stats(daily_close: pd.Series) -> dict[str, float]:
    """Annualized return/vol/Sharpe and drawdown for a daily close series."""
    r = daily_close.pct_change().dropna()
    equity = (1 + r).cumprod()
    peak = equity.cummax()
    dd = (equity / peak - 1.0).min()
    return {
        "n_days": int(len(daily_close)),
        "total_return_pct": float((daily_close.iloc[-1] / daily_close.iloc[0] - 1) * 100),
        "ann_return_pct": float(r.mean() * TRADING_DAYS * 100),
        "ann_vol_pct": float(r.std() * np.sqrt(TRADING_DAYS) * 100),
        "sharpe_naive": float(r.mean() / r.std() * np.sqrt(TRADING_DAYS)) if r.std() else 0.0,
        "pct_up_days": float((r > 0).mean() * 100),
        "max_drawdown_pct": float(dd * 100),
        "best_day_pct": float(r.max() * 100),
        "worst_day_pct": float(r.min() * 100),
    }


def _variance_ratio(daily_close: pd.Series, q: int) -> float:
    """Lo-MacKinlay variance ratio VR(q): var of q-day returns / q * var of 1-day.

    VR>1 => trending (returns positively autocorrelated); VR<1 => mean-reverting;
    VR~1 => random walk. A compact, standard trend-vs-reversion diagnostic.
    """
    logp = np.log(daily_close.to_numpy(dtype=float))
    r1 = np.diff(logp)
    rq = logp[q:] - logp[:-q]
    v1 = np.var(r1, ddof=1)
    vq = np.var(rq, ddof=1)
    return float(vq / (q * v1)) if v1 > 0 else float("nan")


def _overnight_intraday_decomp(df_intraday: pd.DataFrame) -> dict[str, float]:
    """Split daily open->close (intraday) vs prior close->open (overnight) returns."""
    day_open = df_intraday.groupby("date")["open"].first()
    day_close = df_intraday.groupby("date")["close"].last()
    o2c = (day_close / day_open - 1.0).dropna()
    prev_close = day_close.shift(1)
    overnight = (day_open / prev_close - 1.0).dropna()
    return {
        "overnight_ann_return_pct": float(overnight.mean() * TRADING_DAYS * 100),
        "overnight_pct_up": float((overnight > 0).mean() * 100),
        "intraday_o2c_ann_return_pct": float(o2c.mean() * TRADING_DAYS * 100),
        "intraday_o2c_pct_up": float((o2c > 0).mean() * 100),
        "overnight_share_of_c2c_var_pct": float(
            overnight.var() / (overnight.var() + o2c.var()) * 100
        ),
    }


def _holding_period_forward(daily_close: pd.Series, horizons: tuple[int, ...]) -> dict[str, dict]:
    """Forward N-day return distribution: is there drift rewarding longer holds?"""
    out: dict[str, dict] = {}
    for h in horizons:
        fwd = daily_close.shift(-h) / daily_close - 1.0
        fwd = fwd.dropna()
        out[f"{h}d"] = {
            "mean_pct": float(fwd.mean() * 100),
            "median_pct": float(fwd.median() * 100),
            "pct_positive": float((fwd > 0).mean() * 100),
            "std_pct": float(fwd.std() * 100),
        }
    return out


def _dip_conditional(daily_close: pd.Series) -> dict[str, dict]:
    """Next-day return conditioned on N consecutive down closes (mean-reversion signature)."""
    r = daily_close.pct_change()
    down = r < 0
    out: dict[str, dict] = {}
    nxt = r.shift(-1)
    for n in (1, 2, 3):
        streak = down.copy()
        for k in range(1, n):
            streak = streak & down.shift(k, fill_value=False)
        cond = nxt[streak.fillna(False)]
        out[f"after_{n}_down"] = {
            "count": int(len(cond)),
            "next_day_mean_bps": float(cond.mean() * 1e4),
            "next_day_pct_up": float((cond > 0).mean() * 100),
        }
    base = nxt.dropna()
    out["unconditional"] = {
        "count": int(len(base)),
        "next_day_mean_bps": float(base.mean() * 1e4),
        "next_day_pct_up": float((base > 0).mean() * 100),
    }
    return out


def analyze() -> dict[str, object]:
    """Compute the full multi-timeframe market-structure report."""
    out: dict[str, object] = {}

    daily, dropped_d = load_clean_bars(CACHE_DIR, timeframe="1Day")
    dc_full = _daily_close(daily)
    dc_bull = _daily_close(restrict_to_period(daily, start=FOCUS_START, end=FOCUS_END))

    out["daily_return_stats"] = {
        "full_2016_2026": _return_stats(dc_full),
        "focus_2025_2026": _return_stats(dc_bull),
    }

    # Trend vs mean-reversion: variance ratios at several horizons.
    out["variance_ratio_full"] = {f"vr_{q}d": _variance_ratio(dc_full, q) for q in (2, 5, 10, 20)}
    out["variance_ratio_bull"] = {f"vr_{q}d": _variance_ratio(dc_bull, q) for q in (2, 5, 10, 20)}

    # Daily autocorrelation (short-horizon momentum vs reversion).
    r_full = dc_full.pct_change().dropna()
    out["daily_autocorrelation_full"] = {
        f"lag_{lag}": float(r_full.autocorr(lag)) for lag in (1, 2, 3, 5, 10)
    }

    # Holding-period drift and dip conditionals.
    out["forward_return_by_hold_full"] = _holding_period_forward(dc_full, (1, 3, 5, 10, 20, 60))
    out["forward_return_by_hold_bull"] = _holding_period_forward(dc_bull, (1, 3, 5, 10, 20, 60))
    out["dip_conditional_full"] = _dip_conditional(dc_full)
    out["dip_conditional_bull"] = _dip_conditional(dc_bull)

    # Overnight vs intraday decomposition on the 15-minute frame (2025-2026).
    intraday, dropped_i = load_clean_bars(CACHE_DIR, timeframe="15Min")
    out["overnight_vs_intraday_15m"] = _overnight_intraday_decomp(intraday)

    # Per-year buy & hold return + drawdown (regime map) and 2x margin-call flag.
    per_year: dict[str, dict] = {}
    for y in range(2016, 2027):
        seg = restrict_to_period(daily, start=date(y, 1, 1), end=date(y, 12, 31))
        if seg["date"].nunique() < 40:
            continue
        stats = _return_stats(_daily_close(seg))
        # Reg T 2x: a fixed-fraction 2x long is margin-called when the underlying
        # falls >33.3% (equity=50% of notional, 25% maintenance).
        stats["two_x_margin_call"] = bool(abs(stats["max_drawdown_pct"]) > 33.3)
        per_year[str(y)] = stats
    out["buy_hold_by_year"] = per_year

    out["_meta"] = {
        "daily_range": [str(daily["date"].min()), str(daily["date"].max())],
        "daily_dropped_corrupt": [str(d) for d in dropped_d],
        "intraday_dropped_corrupt": [str(d) for d in dropped_i],
        "reg_t_2x_margin_call_underlying_drawdown_pct": 33.3,
    }
    return out, dc_full, per_year  # type: ignore[return-value]


def make_charts(dc_full: pd.Series, per_year: dict[str, dict]) -> list[str]:
    """Render an equity/drawdown chart and a per-year regime chart."""
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []

    r = dc_full.pct_change().fillna(0)
    equity = (1 + r).cumprod()
    peak = equity.cummax()
    dd = equity / peak - 1.0
    x = pd.to_datetime(pd.Index(dc_full.index))

    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True, height_ratios=[2, 1])
    axes[0].plot(x, equity.to_numpy(), color="tab:blue")
    axes[0].set_ylabel("growth of $1 (buy & hold)")
    axes[0].set_title("SPY buy & hold 2016->2026: equity and drawdown")
    axes[0].grid(True, alpha=0.3)
    axes[1].fill_between(x, dd.to_numpy() * 100, 0, color="tab:red", alpha=0.5)
    axes[1].axhline(-33.3, color="black", lw=0.8, ls="--", label="Reg T 2x margin-call level")
    axes[1].set_ylabel("drawdown %")
    axes[1].legend(loc="lower left", fontsize=8)
    axes[1].grid(True, alpha=0.3)
    fig.tight_layout()
    p1 = CHARTS_DIR / "buy_hold_equity_drawdown.png"
    fig.savefig(p1, dpi=110)
    plt.close(fig)
    paths.append(str(p1))

    years = list(per_year.keys())
    rets = [per_year[y]["ann_return_pct"] for y in years]
    dds = [per_year[y]["max_drawdown_pct"] for y in years]
    fig, ax = plt.subplots(figsize=(11, 4))
    xi = np.arange(len(years))
    ax.bar(xi - 0.2, rets, width=0.4, label="annual return %", color="tab:green")
    ax.bar(xi + 0.2, dds, width=0.4, label="max drawdown %", color="tab:red")
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(xi)
    ax.set_xticklabels(years)
    ax.set_title("SPY buy & hold by year: return vs drawdown (regime map)")
    ax.legend(fontsize=8)
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    p2 = CHARTS_DIR / "buy_hold_by_year.png"
    fig.savefig(p2, dpi=110)
    plt.close(fig)
    paths.append(str(p2))
    return paths


def main() -> None:
    result, dc_full, per_year = analyze()  # type: ignore[misc]
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / "swing_market_structure.json"
    out.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    charts = make_charts(dc_full, per_year)

    print("=== SPY multi-timeframe market structure ===")
    print(json.dumps(result["daily_return_stats"], indent=2))
    print("variance_ratio_full:", result["variance_ratio_full"])
    print("overnight_vs_intraday_15m:", result["overnight_vs_intraday_15m"])
    print("charts:", charts)
    print("wrote", out)


if __name__ == "__main__":
    main()
