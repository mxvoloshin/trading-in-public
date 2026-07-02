"""Full momentum/rotation study: rotation baselines + the trend-timed leveraged
candidate, with OOS split, cost/slippage sensitivity, and execution-delay stress.

Writes machine-readable results to research/results/momentum_*.{json,csv}.

Run:
    uv run python research/momentum/run_momentum.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research"))
from momentum.lib import (  # noqa: E402
    CostModel,
    buy_and_hold,
    compute_metrics,
    load_close_panel,
    run_rotation,
    run_trend_timed,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
RESULTS = REPO_ROOT / "research" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

ALL = [
    "SPY",
    "QQQ",
    "IWM",
    "EFA",
    "EEM",
    "XLK",
    "XLE",
    "XLF",
    "XLV",
    "XLY",
    "XLP",
    "XLI",
    "XLU",
    "XLB",
    "XLRE",
    "XLC",
    "TLT",
    "IEF",
    "LQD",
    "HYG",
    "SHY",
    "GLD",
    "VNQ",
    "DBC",
]
LEV = ["SPY", "QQQ", "QLD", "TQQQ", "SSO", "UPRO", "BIL"]
SECTORS = ["XLK", "XLE", "XLF", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"]
ASSETS = ["SPY", "QQQ", "EFA", "EEM", "TLT", "IEF", "GLD", "VNQ", "DBC", "HYG"]

FULL_START = "2017-01-03"  # after 12-mo momentum / 200d SMA warmup
TRAIN = ("2017-01-03", "2020-12-31")
TEST = ("2021-01-01", "2026-07-01")  # includes the 2022 bear + 2025 drawdown


def main() -> int:
    panel_all = load_close_panel(ALL)
    panel_lev = load_close_panel(LEV)
    default_cost = CostModel(commission_bps=5, slippage_bps=3)
    rows: list[dict] = []

    def add(m, extra=None):
        row = m.to_row()
        if extra:
            row.update(extra)
        rows.append(row)

    # --- Benchmarks -------------------------------------------------------
    for sym in ["SPY", "QQQ", "TQQQ"]:
        r, e = buy_and_hold(panel_lev, sym, start=FULL_START)
        add(compute_metrics(r, e, label=f"BENCH {sym} buy&hold"), {"group": "benchmark"})

    # --- Rotation baselines (unleveraged; the honest 'no edge' result) ----
    def rot(name, universe, **kw):
        sa = kw.get("safe_asset")
        u = list(universe) + ([sa] if sa and sa not in universe else [])
        res = run_rotation(panel_all[u], start=FULL_START, cost=CostModel(), **kw)
        add(
            compute_metrics(
                res.daily_returns, res.equity, label=name, holdings_log=res.holdings_log
            ),
            {"group": "rotation"},
        )

    rot("ROT sector top3 6mo", SECTORS, lookback_days=126, top_k=3)
    rot("ROT sector top3 12-1", SECTORS, lookback_days=252, top_k=3, skip_days=21)
    rot(
        "ROT asset top1 12mo dualIEF",
        ASSETS,
        lookback_days=252,
        top_k=1,
        absolute_filter=True,
        safe_asset="IEF",
    )
    rot(
        "ROT asset top3 6mo dualIEF",
        ASSETS,
        lookback_days=126,
        top_k=3,
        absolute_filter=True,
        safe_asset="IEF",
    )

    # --- Trend-timed leveraged candidate: MA robustness (full period) -----
    for base, lev in [("QQQ", "QLD"), ("QQQ", "TQQQ"), ("SPY", "SSO"), ("SPY", "UPRO")]:
        for ma in [150, 175, 200, 225]:
            r, e, n = run_trend_timed(
                panel_lev, base=base, lev=lev, ma=ma, cost=default_cost, start=FULL_START
            )
            add(
                compute_metrics(r, e, label=f"TREND {lev}/{base}>SMA{ma}"),
                {"group": "trend_full", "switches": n},
            )

    # --- Focus candidate: QLD/QQQ>SMA200 — OOS split ----------------------
    def focus_variants():
        return [("QLD", "QQQ", 200), ("QLD", "QQQ", 175), ("TQQQ", "QQQ", 200)]

    for lev, base, ma in focus_variants():
        # Train
        r, e, n = run_trend_timed(
            panel_lev, base=base, lev=lev, ma=ma, cost=default_cost, start=TRAIN[0], end=TRAIN[1]
        )
        add(
            compute_metrics(r, e, label=f"OOS-TRAIN {lev}/{base}>SMA{ma}"),
            {"group": "oos", "switches": n},
        )
        # Test (out of sample)
        r, e, n = run_trend_timed(
            panel_lev, base=base, lev=lev, ma=ma, cost=default_cost, start=TEST[0], end=TEST[1]
        )
        add(
            compute_metrics(r, e, label=f"OOS-TEST {lev}/{base}>SMA{ma}"),
            {"group": "oos", "switches": n},
        )

    # --- Cost & slippage sensitivity on the focus candidate ---------------
    for cbps, sbps, tag in [
        (0, 0, "zero"),
        (5, 3, "base"),
        (10, 6, "2x"),
        (20, 12, "4x"),
        (35, 25, "stress"),
    ]:
        c = CostModel(commission_bps=cbps, slippage_bps=sbps)
        r, e, n = run_trend_timed(
            panel_lev, base="QQQ", lev="QLD", ma=200, cost=c, start=FULL_START
        )
        add(
            compute_metrics(r, e, label=f"COST QLD/QQQ>SMA200 {tag}({cbps}+{sbps}bp)"),
            {"group": "cost", "switches": n},
        )

    # --- Execution-delay stress (act 1 vs 2 days late) --------------------
    for lag in [1, 2, 3]:
        r, e, n = run_trend_timed(
            panel_lev,
            base="QQQ",
            lev="QLD",
            ma=200,
            cost=default_cost,
            signal_lag=lag,
            start=FULL_START,
        )
        add(
            compute_metrics(r, e, label=f"LAG QLD/QQQ>SMA200 lag{lag}d"),
            {"group": "exec_lag", "switches": n},
        )

    # --- Persist ----------------------------------------------------------
    df = pd.DataFrame(rows)
    (RESULTS / "momentum_results.json").write_text(json.dumps(rows, indent=2, default=str))
    df.to_csv(RESULTS / "momentum_results.csv", index=False)

    # Save the focus candidate's daily equity for the report chart / audit.
    r, e, n = run_trend_timed(
        panel_lev, base="QQQ", lev="QLD", ma=200, cost=default_cost, start=FULL_START
    )
    rb, eb = buy_and_hold(panel_lev, "QQQ", start=FULL_START)
    rs, es = buy_and_hold(panel_lev, "SPY", start=FULL_START)
    eq = pd.DataFrame({"QLD_QQQ_SMA200": e, "QQQ_BH": eb, "SPY_BH": es}).dropna()
    eq.to_csv(RESULTS / "momentum_equity_focus.csv")

    cols = [
        "group",
        "label",
        "cagr_pct",
        "ann_vol_pct",
        "sharpe",
        "sortino",
        "max_drawdown_pct",
        "calmar",
        "switches",
    ]
    show = df.reindex(columns=cols)
    with pd.option_context("display.max_rows", None, "display.width", 200):
        print(show.to_string(index=False))
    print(f"\nWrote {RESULTS / 'momentum_results.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
