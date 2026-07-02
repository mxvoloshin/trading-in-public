"""Single-stock cross-sectional momentum study (2020 -> now).

Prior tracks found no edge ranking *sector ETFs* cross-sectionally. This tests the
much stronger *single-stock* momentum factor on a broad large-cap universe, with a
market-trend regime overlay, parameter sweeps, an out-of-sample split, per-year
walk-forward, and cost stress.

Reuses the audited portfolio simulator in ``research/momentum/lib.py`` (symbol-
agnostic): ``load_close_panel``, ``run_rotation``, ``compute_metrics``,
``buy_and_hold``. Adds only a regime-filter wrapper on top.

No lookahead: momentum ranks on closes up to a month-end ``t``; weights are held the
FOLLOWING month; the regime gate uses SPY vs its SMA lagged one day.

Run:
    uv run python research/stocks/run_stocks.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research"))
from momentum.lib import (  # noqa: E402
    CostModel,
    buy_and_hold,
    compute_metrics,
    load_close_panel,
    run_rotation,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / ".data" / "stocks_adj"
RESULTS = REPO_ROOT / "research" / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

# Study window per the constraint: trade from 2020 onward.
STUDY_START = "2020-01-01"
# Out-of-sample split: train the parameter choice on 2020-2022, confirm on 2023+.
TRAIN_END = "2022-12-31"
TEST_START = "2023-01-01"

BENCH = ["SPY", "QQQ"]  # excluded from the tradable stock universe (used as benchmarks/regime)


def stock_universe(panel: pd.DataFrame) -> list[str]:
    """Tradable single-stock columns (everything except the benchmark ETFs)."""
    return [c for c in panel.columns if c not in BENCH]


# --------------------------------------------------------------------------
# Regime overlay: hold the momentum sleeve only while SPY is in an uptrend.
# --------------------------------------------------------------------------
def regime_mask(panel: pd.DataFrame, *, ma: int = 200, lag: int = 1) -> pd.Series:
    """Boolean daily series: True when SPY close > its SMA(ma), lagged ``lag`` days.

    Lagging removes lookahead — today's holding is decided by yesterday's close vs
    its SMA. Days before enough history exist are treated as risk-off (False).
    """
    spy = panel["SPY"]
    sma = spy.rolling(ma).mean()
    # ``> `` yields a real bool Series; shift introduces NaN for the first `lag` rows,
    # so fill those as risk-off before casting back to a clean boolean series.
    signal = (spy > sma).shift(lag)
    return signal.astype("boolean").fillna(False).astype(bool)


def apply_regime(
    base_returns: pd.Series,
    panel: pd.DataFrame,
    *,
    ma: int = 200,
    cost: CostModel | None = None,
) -> pd.Series:
    """Overlay a market-trend filter on a rotation's net daily returns.

    When the regime is risk-off we sit in cash (0% return) instead of the momentum
    sleeve. A whole-portfolio flip in/out of cash is charged one round trip
    (2 sides) on the day the regime changes — conservative, since we still let the
    underlying rotation book its own rebalance costs while invested.
    """
    cost = cost or CostModel()
    regime = regime_mask(panel, ma=ma).reindex(base_returns.index).fillna(False)
    out = base_returns.where(regime, 0.0)
    flip = regime.astype(int).diff().abs().fillna(0.0)
    out = out - flip * 2.0 * cost.per_side_frac
    return out


@dataclass(frozen=True, slots=True)
class Variant:
    label: str
    lookback: int
    top_k: int
    skip: int
    trend_filter: bool


def run_variant(
    panel: pd.DataFrame,
    v: Variant,
    *,
    cost: CostModel,
    start: str,
    end: str | None = None,
    init_cash: float = 2_000.0,
):
    """Run one momentum variant and return (net_daily_returns, equity)."""
    tradable = stock_universe(panel)
    # Rank only the single stocks; the regime overlay handles risk-off, so no safe
    # asset is passed to run_rotation (it stays fully invested in the top-K).
    res = run_rotation(
        panel[tradable],
        lookback_days=v.lookback,
        top_k=v.top_k,
        skip_days=v.skip,
        cost=cost,
        init_cash=init_cash,
        start=start,
    )
    ret = res.daily_returns
    if v.trend_filter:
        ret = apply_regime(ret, panel, ma=200, cost=cost)
    if end is not None:
        ret = ret[ret.index <= pd.Timestamp(end)]
    ret = ret.fillna(0.0)
    equity = init_cash * (1.0 + ret).cumprod()
    return ret, equity


def metrics_for(ret: pd.Series, equity: pd.Series, label: str):
    return compute_metrics(ret, equity, label=label)


def main() -> int:
    panel = load_close_panel(sorted(set(stock_universe_symbols())), cache_dir=CACHE_DIR)
    # Drop any all-NaN rows and require the benchmarks be present.
    panel = panel.dropna(how="all")
    tradable = stock_universe(panel)
    print(
        f"Universe: {len(tradable)} stocks + {len(BENCH)} benchmarks, "
        f"{panel.index[0].date()} -> {panel.index[-1].date()}"
    )

    rows: list[dict] = []

    # ---- Benchmarks (2020 -> now) ----
    for b in BENCH:
        ret, eq = buy_and_hold(panel, b, start=STUDY_START)
        rows.append(metrics_for(ret, eq, f"BUYHOLD {b}").to_row())

    # ---- Parameter sweep, full window (2020 -> now) ----
    cost = CostModel()  # 5 bp comm + 2 bp slip per side (small IBKR account)
    sweep: list[Variant] = []
    for lookback in (63, 126, 189, 252):
        for top_k in (3, 5, 10):
            for skip in (0, 21):
                for tf in (False, True):
                    tag = f"L{lookback}_K{top_k}_S{skip}_{'TF' if tf else 'raw'}"
                    sweep.append(Variant(tag, lookback, top_k, skip, tf))

    best_full: tuple[float, Variant] | None = None
    for v in sweep:
        ret, eq = run_variant(panel, v, cost=cost, start=STUDY_START)
        m = metrics_for(ret, eq, v.label)
        rows.append(m.to_row())
        if best_full is None or m.cagr_pct > best_full[0]:
            best_full = (m.cagr_pct, v)

    # ---- Train/test integrity: pick best by TRAIN Sharpe, report its TEST perf ----
    train_scores: list[tuple[float, Variant]] = []
    for v in sweep:
        ret, eq = run_variant(panel, v, cost=cost, start=STUDY_START, end=TRAIN_END)
        m = metrics_for(ret, eq, v.label + "_train")
        train_scores.append((m.sharpe, v))
    train_scores.sort(key=lambda t: np.nan_to_num(t[0], nan=-1e9), reverse=True)
    picked = train_scores[0][1]

    oos_report: dict = {}
    for phase, (s, e) in {
        "train_2020_2022": (STUDY_START, TRAIN_END),
        "test_2023_now": (TEST_START, None),
        "full_2020_now": (STUDY_START, None),
    }.items():
        ret, eq = run_variant(panel, picked, cost=cost, start=s, end=e)
        oos_report[phase] = metrics_for(ret, eq, f"PICKED {picked.label} {phase}").to_row()

    # ---- Per-year walk-forward of the picked variant (full-window signals) ----
    ret_full, _ = run_variant(panel, picked, cost=cost, start=STUDY_START)
    per_year: dict[str, float] = {}
    for yr, grp in ret_full.groupby(ret_full.index.year):
        per_year[str(yr)] = round(float((1.0 + grp).prod() - 1.0) * 100, 2)

    # ---- Shortlist OOS: for the strongest variants, report train + test + full ----
    # A variant is only credible if it survives the 2023+ out-of-sample window, not
    # just the 2020-2021 mega-bull. Rank by full-window Sharpe and re-run each split.
    def variant_from_label(lbl: str) -> Variant | None:
        return next((v for v in sweep if v.label == lbl), None)

    df_full = pd.DataFrame(rows)
    df_stocks = df_full[~df_full["label"].str.startswith("BUYHOLD")]
    shortlist_labels = list(df_stocks.sort_values("sharpe", ascending=False)["label"].head(8))
    shortlist: dict[str, dict] = {}
    for lbl in shortlist_labels:
        v = variant_from_label(lbl)
        if v is None:
            continue
        entry: dict[str, dict] = {}
        for phase, (s, e) in {
            "train_2020_2022": (STUDY_START, TRAIN_END),
            "test_2023_now": (TEST_START, None),
            "full_2020_now": (STUDY_START, None),
        }.items():
            r, eqp = run_variant(panel, v, cost=cost, start=s, end=e)
            mm = metrics_for(r, eqp, f"{lbl}_{phase}")
            entry[phase] = {
                "cagr_pct": mm.cagr_pct,
                "sharpe": mm.sharpe,
                "max_dd_pct": mm.max_drawdown_pct,
                "calmar": mm.calmar,
            }
        shortlist[lbl] = entry

    print("\n=== Shortlist (ranked by full-window Sharpe): train / test / full ===")
    print(
        f"{'variant':18s} {'train CAGR':>10s} {'test CAGR':>10s} {'full CAGR':>10s} "
        f"{'test Shrp':>9s} {'test DD':>8s}"
    )
    for lbl, e in shortlist.items():
        print(
            f"{lbl:18s} {e['train_2020_2022']['cagr_pct']:9.1f}% "
            f"{e['test_2023_now']['cagr_pct']:9.1f}% {e['full_2020_now']['cagr_pct']:9.1f}% "
            f"{e['test_2023_now']['sharpe']:9.2f} {e['test_2023_now']['max_dd_pct']:7.1f}%"
        )

    # ---- Cost stress on the picked variant (full window) ----
    cost_grid: dict[str, dict] = {}
    for cbps, sbps in [(2, 1), (5, 2), (10, 5), (20, 10)]:
        c = CostModel(commission_bps=cbps, slippage_bps=sbps)
        ret, eq = run_variant(panel, picked, cost=c, start=STUDY_START)
        m = metrics_for(ret, eq, f"cost_{cbps}_{sbps}")
        cost_grid[f"comm{cbps}_slip{sbps}"] = {
            "cagr_pct": m.cagr_pct,
            "sharpe": m.sharpe,
            "max_dd_pct": m.max_drawdown_pct,
        }

    # ---- Report ----
    df = pd.DataFrame(rows)
    df_sorted = df.sort_values("cagr_pct", ascending=False)
    print("\n=== Top 15 by full-window CAGR (2020 -> now, net) ===")
    cols = [
        "label",
        "cagr_pct",
        "ann_vol_pct",
        "sharpe",
        "sortino",
        "max_drawdown_pct",
        "calmar",
        "pct_months_positive",
    ]
    print(df_sorted[cols].head(15).to_string(index=False))

    print(f"\n=== Picked-by-train variant: {picked.label} ===")
    for phase, m in oos_report.items():
        print(
            f"  {phase:16s} CAGR {m['cagr_pct']:6.2f}%  Sharpe {m['sharpe']:.2f}  "
            f"MaxDD {m['max_drawdown_pct']:6.2f}%  Calmar {m['calmar']}"
        )
    print("  per-year:", per_year)
    print("  cost stress:", json.dumps(cost_grid))

    # ---- Persist ----
    df_sorted.to_csv(RESULTS / "stocks_sweep.csv", index=False)
    (RESULTS / "stocks_summary.json").write_text(
        json.dumps(
            {
                "universe_size": len(tradable),
                "window": [str(panel.index[0].date()), str(panel.index[-1].date())],
                "picked_variant": asdict(picked),
                "oos": oos_report,
                "per_year": per_year,
                "cost_stress": cost_grid,
                "shortlist_oos": shortlist,
                "best_full_by_cagr": {"cagr_pct": best_full[0], "variant": asdict(best_full[1])},
            },
            indent=2,
        )
    )
    print(f"\nWrote {RESULTS / 'stocks_sweep.csv'} and {RESULTS / 'stocks_summary.json'}")
    return 0


def stock_universe_symbols() -> list[str]:
    """All symbols to load: import the fetch universe so the two stay in sync."""
    from stocks.fetch_stocks import ALL_SYMBOLS

    return ALL_SYMBOLS


if __name__ == "__main__":
    raise SystemExit(main())
