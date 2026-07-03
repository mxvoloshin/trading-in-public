"""Diagnose *why* gap-and-go worked in 2020-2026 but not 2016-2019 — and what to fix.

Three analyses, all reproducible, written to research/results/mes_regime_diagnosis.json:

1. **Per-year long/short decomposition + regime context.** Splits the keeper's P&L into
   long vs short by year alongside SPY's annual drift and realized volatility. Shows the
   strategy is a *trend-day harvester*: it prints in trending years (2021 long, 2022 short)
   and bleeds in choppy / reversal years — volatility alone does not explain it.

2. **Follow-through by gap size (the mechanism).** For every day, measures how far price
   travels from the entry area (~09:40) to the 13:00 exit *in the gap's direction*, bucketed
   by gap size. The edge lives entirely in **large gaps (>0.5%)**; small gaps (<0.3%) are
   coin-flips with zero-to-negative expectancy — and this split holds in *both* eras. The
   baseline strategy diluted a real large-gap edge with a flood of no-edge small-gap noise.

3. **The fix.** Compares the baseline (gap>0.15%) to a selective variant (gap>0.5%) across
   the full sample, the 2016-2019 out-of-sample window, and 2020-2026 — including drawdown,
   survivability, and per-year P&L.

Run: uv run python research/mes_intraday/diagnose_regime.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from research.lib.data_access import load_spy_5min  # noqa: E402
from research.mes_intraday.exits import ExitPolicy, simulate_with_exits  # noqa: E402
from research.mes_intraday.lib import (  # noqa: E402
    INTRADAY_MARGIN_PER_CONTRACT,
    LSSignals,
    compute_metrics,
    flag_corrupt_days_local,
)
from research.mes_intraday.novel import _day_features, gap_and_go  # noqa: E402

RESULTS_DIR = Path("research/results")
COMM, SLIP = "mid", "one"
POLICY = ExitPolicy(label="x", stop_atr=1.0, time_exit=(13, 0))
SPLIT = pd.Timestamp("2020-01-01").date()


def _load():
    df = load_spy_5min(Path(".data"))
    bad = flag_corrupt_days_local(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()
    return df


def _metrics(df, sig, frame=None):
    frame = df if frame is None else frame
    idx = frame.index
    s = LSSignals(
        sig.entry_long.loc[idx],
        sig.exit_long.loc[idx],
        sig.entry_short.loc[idx],
        sig.exit_short.loc[idx],
    )
    trades = simulate_with_exits(
        frame,
        s.entry_long,
        s.entry_short,
        POLICY,
        contracts=1,
        commission_scenario=COMM,
        slippage_scenario=SLIP,
    )
    return compute_metrics(
        frame, trades, label="x", contracts=1, commission_scenario=COMM, slippage_scenario=SLIP
    ), trades


def analysis_1_long_short(df) -> list[dict]:
    """Per-year long/short P&L split + SPY drift and daily vol (regime context)."""
    _m, trades = _metrics(df, gap_and_go(df))
    tr = pd.DataFrame(
        [
            {
                "year": t.exit_ts.tz_convert("America/New_York").year,
                "dir": t.direction,
                "pnl": t.pnl,
            }
            for t in trades
        ]
    )
    dc = df.groupby("date")["close"].last()
    dret = dc.pct_change()
    dyear = pd.Series([d.year for d in dc.index], index=dc.index)
    rows = []
    for y in range(2016, 2027):
        g = tr[tr["year"] == y]
        gl, gs = g[g["dir"] == 1], g[g["dir"] == -1]
        yr_close = dc[dyear == y]
        spy_ret = float((yr_close.iloc[-1] / yr_close.iloc[0] - 1) * 100) if len(yr_close) else None
        rows.append(
            {
                "year": y,
                "long_pnl": round(float(gl["pnl"].sum()), 0),
                "short_pnl": round(float(gs["pnl"].sum()), 0),
                "total_pnl": round(float(g["pnl"].sum()), 0),
                "spy_return_pct": round(spy_ret, 1) if spy_ret is not None else None,
                "daily_vol_pct": round(float(dret[dyear == y].std() * 100), 2),
            }
        )
    return rows


def analysis_2_gap_buckets(df) -> dict:
    """Follow-through (entry ~09:40 -> 13:00, in gap direction) by gap-size bucket, and by era."""
    loc = df.index.tz_convert("America/New_York")
    d2 = df.assign(_h=loc.hour, _m=loc.minute)
    entry_px = d2.groupby("date")["close"].apply(lambda s: s.iloc[1] if len(s) > 1 else np.nan)
    at13 = d2[(d2["_h"] == 13) & (d2["_m"] == 0)].groupby("date")["close"].first()

    f = _day_features(df)
    f["entry_px"], f["exit_px"] = entry_px, at13
    f = f.dropna(subset=["gap", "entry_px", "exit_px"]).copy()
    f["dir"] = np.sign(f["gap"])
    # Signed continuation in the gap direction, in basis points.
    f["cont_bps"] = ((f["exit_px"] - f["entry_px"]) / f["entry_px"]) * f["dir"] * 1e4
    f["win"] = f["cont_bps"] > 0
    f["absgap"] = f["gap"].abs() * 100
    f["year"] = [d.year for d in f.index]

    buckets = []
    for lo, hi in [(0, 0.15), (0.15, 0.3), (0.3, 0.5), (0.5, 0.8), (0.8, 9)]:
        b = f[(f["absgap"] >= lo) & (f["absgap"] < hi)]
        buckets.append(
            {
                "bucket": f"{lo:.2f}-{hi:.2f}%",
                "n": int(len(b)),
                "continued_pct": round(float(b["win"].mean() * 100), 1),
                "avg_cont_bps": round(float(b["cont_bps"].mean()), 1),
                "median_cont_bps": round(float(b["cont_bps"].median()), 1),
            }
        )
    by_era = {}
    for label, cut in [
        ("big_gap_gt_0.5", f["absgap"] >= 0.5),
        ("small_gap_lt_0.3", f["absgap"] < 0.3),
    ]:
        sub = f[cut]
        by_era[label] = {
            era: {
                "n": int(len(s)),
                "continued_pct": round(float(s["win"].mean() * 100), 1),
                "avg_cont_bps": round(float(s["cont_bps"].mean()), 1),
            }
            for era, s in [
                ("2016-2019", sub[sub["year"] < 2020]),
                ("2020-2026", sub[sub["year"] >= 2020]),
            ]
        }
    return {"buckets": buckets, "by_era": by_era}


def analysis_3_fix(df) -> list[dict]:
    """Baseline vs the selective gap>0.5% fix, across FULL / OOS 2016-19 / DEV 2020-26."""
    oos = df[df["date"] < SPLIT]
    dev = df[df["date"] >= SPLIT]
    out = []
    for label, thr in [("baseline gap>0.15%", 0.0015), ("fix: gap>0.5%", 0.005)]:
        sig = gap_and_go(df, gap_thr=thr)
        mf, _ = _metrics(df, sig)
        mo, _ = _metrics(df, sig, oos)
        md, _ = _metrics(df, sig, dev)
        out.append(
            {
                "variant": label,
                "full_annual_pct": mf.annual_return_pct,
                "full_total_pnl": mf.total_pnl,
                "full_max_dd_pct": mf.max_drawdown_pct,
                "full_min_equity": mf.min_equity,
                "survives_2k": mf.min_equity >= INTRADAY_MARGIN_PER_CONTRACT,
                "oos_annual_pct": mo.annual_return_pct,
                "oos_total_pnl": mo.total_pnl,
                "dev_annual_pct": md.annual_return_pct,
                "trades": mf.total_trades,
                "per_year": mf.per_year,
            }
        )
    return out


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df = _load()
    a1 = analysis_1_long_short(df)
    a2 = analysis_2_gap_buckets(df)
    a3 = analysis_3_fix(df)
    out = {"long_short_by_year": a1, "gap_bucket_followthrough": a2, "baseline_vs_fix": a3}
    (RESULTS_DIR / "mes_regime_diagnosis.json").write_text(json.dumps(out, indent=2, default=str))

    print("=== 1. Per-year long/short split + regime context ===")
    print(f"{'yr':4s} {'long$':>7s} {'short$':>7s} {'total$':>7s} {'SPY%':>6s} {'dVol%':>6s}")
    for r in a1:
        print(
            f"{r['year']:<4d} {r['long_pnl']:>7.0f} {r['short_pnl']:>7.0f} {r['total_pnl']:>7.0f} "
            f"{(r['spy_return_pct'] or 0):>6.1f} {r['daily_vol_pct']:>6.2f}"
        )

    print("\n=== 2. Follow-through by gap size (the mechanism) ===")
    print(f"{'|gap|':>12s} {'n':>5s} {'contd%':>7s} {'avgBps':>7s} {'medBps':>7s}")
    for b in a2["buckets"]:
        print(
            f"{b['bucket']:>12s} {b['n']:>5d} {b['continued_pct']:>7.1f} "
            f"{b['avg_cont_bps']:>7.1f} {b['median_cont_bps']:>7.1f}"
        )
    print("  edge by era:", json.dumps(a2["by_era"]))

    print("\n=== 3. Baseline vs fix ===")
    for r in a3:
        print(
            f"{r['variant']:20s} FULL {r['full_annual_pct']:5.1f}% "
            f"(${r['full_total_pnl']:.0f}, DD {r['full_max_dd_pct']:.0f}%, "
            f"minEq ${r['full_min_equity']:.0f}, survive {r['survives_2k']})  "
            f"OOS {r['oos_annual_pct']:5.1f}%  DEV {r['dev_annual_pct']:5.1f}%  "
            f"({r['trades']} trades)"
        )


if __name__ == "__main__":
    main()
