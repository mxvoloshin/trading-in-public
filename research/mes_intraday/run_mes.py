"""Run the MES intraday strategy study end-to-end and write machine-readable results.

Stages:
  1. Load the full 2020->now SPY 5-minute cache (proxy for MES), robust-clean it.
  2. Run the five well-known intraday strategies + benchmark at the base cost
     scenario, 1 contract, long+short, flat by EOD.
  3. Cost-stress grid (commission x slippage) for every strategy.
  4. Chronological train/test split (70/30) for the survivors.
  5. Contract-scaling view (1/2/3 contracts) for the best strategy — the leverage
     lever a $2,000 futures account actually has.
  6. Dump everything to research/results/mes_*.json|csv.

Run: uv run python research/mes_intraday/run_mes.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

# research/ is imported as a top-level package (research.*); make the repo root
# importable when this script is run directly, mirroring research/run_experiments.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from research.lib.data_access import load_spy_5min  # noqa: E402
from research.mes_intraday.lib import (  # noqa: E402
    INIT_CASH,
    STRATEGIES,
    compute_metrics,
    flag_corrupt_days_local,
    simulate_mes,
)

CACHE_DIR = Path(".data")
RESULTS_DIR = Path("research/results")
BASE_COMMISSION = "mid"
BASE_SLIPPAGE = "one"


def load_clean() -> tuple[pd.DataFrame, list[object]]:
    """Load SPY 5-minute bars for the whole cache and drop any corrupt trade dates."""
    df = load_spy_5min(CACHE_DIR)
    bad = flag_corrupt_days_local(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()
    return df, bad


def run_all(df: pd.DataFrame, *, contracts: int = 1) -> list[dict]:
    """Every strategy at the base cost scenario; returns metric rows."""
    rows: list[dict] = []
    for label, fn in STRATEGIES.items():
        sig = fn(df)
        trades = simulate_mes(
            df,
            sig,
            contracts=contracts,
            commission_scenario=BASE_COMMISSION,
            slippage_scenario=BASE_SLIPPAGE,
        )
        m = compute_metrics(
            df,
            trades,
            label=label,
            contracts=contracts,
            commission_scenario=BASE_COMMISSION,
            slippage_scenario=BASE_SLIPPAGE,
        )
        rows.append({**m.to_row(), "per_year": m.per_year})
    return rows


def run_risk_managed(
    df: pd.DataFrame, *, contracts: int = 1, stop_frac: float = 0.003, target_frac: float = 0.006
) -> list[dict]:
    """Every strategy again, this time with a realistic per-trade stop + target.

    A hard stop is how these setups are actually day-traded and is survival-critical
    for a $2,000 futures account. Default 0.30% stop / 0.60% target (~1:2 reward:risk),
    which at S&P index levels is roughly a $35-100/contract stop across 2020-2026.
    """
    rows: list[dict] = []
    for label, fn in STRATEGIES.items():
        if label.startswith("BENCH"):
            continue
        trades = simulate_mes(
            df,
            fn(df),
            contracts=contracts,
            commission_scenario=BASE_COMMISSION,
            slippage_scenario=BASE_SLIPPAGE,
            stop_frac=stop_frac,
            target_frac=target_frac,
        )
        m = compute_metrics(
            df,
            trades,
            label=label,
            contracts=contracts,
            commission_scenario=BASE_COMMISSION,
            slippage_scenario=BASE_SLIPPAGE,
        )
        rows.append(
            {
                **m.to_row(),
                "per_year": m.per_year,
                "stop_frac": stop_frac,
                "target_frac": target_frac,
            }
        )
    return rows


def stop_sweep(df: pd.DataFrame, label: str, fn) -> list[dict]:
    """Sweep stop/target geometry for one strategy — does any config survive AND hit 20%?"""
    out: list[dict] = []
    for stop in (0.0015, 0.002, 0.003, 0.004, 0.005):
        for rr in (1.0, 1.5, 2.0, 3.0):
            trades = simulate_mes(
                df,
                fn(df),
                contracts=1,
                commission_scenario=BASE_COMMISSION,
                slippage_scenario=BASE_SLIPPAGE,
                stop_frac=stop,
                target_frac=stop * rr,
            )
            m = compute_metrics(
                df,
                trades,
                label=label,
                contracts=1,
                commission_scenario=BASE_COMMISSION,
                slippage_scenario=BASE_SLIPPAGE,
            )
            out.append(
                {
                    "stop_frac": stop,
                    "reward_risk": rr,
                    "annual_return_pct": m.annual_return_pct,
                    "sharpe": m.sharpe,
                    "max_drawdown_pct": m.max_drawdown_pct,
                    "max_drawdown_dollars": m.max_drawdown_dollars,
                    "would_blow_up": m.would_blow_up,
                    "profit_factor": m.profit_factor,
                    "win_rate_pct": m.win_rate_pct,
                }
            )
    return out


def cost_grid(df: pd.DataFrame, label: str, fn) -> list[dict]:
    """Sweep commission x slippage for one strategy (annualized % of $2,000)."""
    grid: list[dict] = []
    for comm in ("none", "low", "mid", "high", "stress"):
        for slip in ("none", "half", "one", "stress"):
            trades = simulate_mes(
                df, fn(df), contracts=1, commission_scenario=comm, slippage_scenario=slip
            )
            m = compute_metrics(
                df,
                trades,
                label=label,
                contracts=1,
                commission_scenario=comm,
                slippage_scenario=slip,
            )
            grid.append(
                {
                    "commission": comm,
                    "slippage": slip,
                    "annual_return_pct": m.annual_return_pct,
                    "total_pnl": m.total_pnl,
                    "sharpe": m.sharpe,
                    "max_drawdown_pct": m.max_drawdown_pct,
                }
            )
    return grid


def train_test(df: pd.DataFrame) -> list[dict]:
    """Chronological 70/30 split by trade date; compare every strategy across halves."""
    dates = sorted(set(df["date"]))
    cut = dates[int(len(dates) * 0.70)]
    train = df[df["date"] < cut].copy()
    test = df[df["date"] >= cut].copy()
    out: list[dict] = []
    for label, fn in STRATEGIES.items():
        row = {"label": label, "split_date": str(cut)}
        for name, part in (("train", train), ("test", test)):
            trades = simulate_mes(
                part,
                fn(part),
                contracts=1,
                commission_scenario=BASE_COMMISSION,
                slippage_scenario=BASE_SLIPPAGE,
            )
            m = compute_metrics(
                part,
                trades,
                label=label,
                contracts=1,
                commission_scenario=BASE_COMMISSION,
                slippage_scenario=BASE_SLIPPAGE,
            )
            row[f"{name}_annual_pct"] = m.annual_return_pct
            row[f"{name}_sharpe"] = m.sharpe
            row[f"{name}_pf"] = m.profit_factor
            row[f"{name}_maxdd_pct"] = m.max_drawdown_pct
        out.append(row)
    return out


def contract_scaling(df: pd.DataFrame, label: str, fn) -> list[dict]:
    """Best strategy at 1/2/3 contracts — the leverage lever, and its ruin cost."""
    out: list[dict] = []
    for n in (1, 2, 3):
        trades = simulate_mes(
            df,
            fn(df),
            contracts=n,
            commission_scenario=BASE_COMMISSION,
            slippage_scenario=BASE_SLIPPAGE,
        )
        m = compute_metrics(
            df,
            trades,
            label=label,
            contracts=n,
            commission_scenario=BASE_COMMISSION,
            slippage_scenario=BASE_SLIPPAGE,
        )
        out.append(
            {
                "contracts": n,
                "annual_return_pct": m.annual_return_pct,
                "total_pnl": m.total_pnl,
                "max_drawdown_pct": m.max_drawdown_pct,
                "max_drawdown_dollars": m.max_drawdown_dollars,
                "worst_day_dollars": m.worst_day_dollars,
                "min_equity": m.min_equity,
                "would_blow_up": m.would_blow_up,
                "sharpe": m.sharpe,
            }
        )
    return out


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df, bad = load_clean()
    days = sorted(set(df["date"]))
    meta = {
        "instrument_proxy": "SPY 5Min -> MES via index=SPYx10, $5/pt",
        "n_bars": int(len(df)),
        "n_days": len(days),
        "first_day": str(days[0]),
        "last_day": str(days[-1]),
        "dropped_corrupt_days": [str(d) for d in bad],
        "init_cash": INIT_CASH,
        "base_commission": BASE_COMMISSION,
        "base_slippage": BASE_SLIPPAGE,
    }

    summary = run_all(df, contracts=1)
    risk_managed = run_risk_managed(df, contracts=1)

    # Pick the best *risk-managed* strategy that does NOT blow up the account, ranked
    # by annualized return; fall back to best risk-managed by return if all blow up.
    survivors = [r for r in risk_managed if not r["would_blow_up"]]
    pool = survivors if survivors else risk_managed
    best = max(pool, key=lambda r: r["annual_return_pct"])
    best_label = best["label"]
    best_fn = STRATEGIES[best_label]

    sweep = stop_sweep(df, best_label, best_fn)
    grid = cost_grid(df, best_label, best_fn)
    splits = train_test(df)
    scaling = contract_scaling(df, best_label, best_fn)

    out = {
        "meta": meta,
        "summary_naive": summary,
        "summary_risk_managed": risk_managed,
        "best_label": best_label,
        "best_survives": not best["would_blow_up"],
        "stop_sweep": sweep,
        "cost_grid": grid,
        "train_test": splits,
        "contract_scaling": scaling,
    }
    (RESULTS_DIR / "mes_summary.json").write_text(json.dumps(out, indent=2, default=str))

    # Flat CSV combining naive + risk-managed rows for quick scanning.
    cols = [
        "mode",
        "label",
        "contracts",
        "annual_return_pct",
        "cagr_pct",
        "total_pnl",
        "sharpe",
        "sortino",
        "max_drawdown_pct",
        "max_drawdown_dollars",
        "calmar",
        "worst_day_dollars",
        "would_blow_up",
        "total_trades",
        "trades_per_day",
        "long_trades",
        "short_trades",
        "win_rate_pct",
        "profit_factor",
        "expectancy",
    ]
    lines = [",".join(cols)]
    for r in summary:
        lines.append("naive," + ",".join(str(r.get(c, "")) for c in cols[1:]))
    for r in risk_managed:
        lines.append("risk_managed," + ",".join(str(r.get(c, "")) for c in cols[1:]))
    (RESULTS_DIR / "mes_summary.csv").write_text("\n".join(lines) + "\n")

    # Console digest.
    def _digest(title: str, rows: list[dict]) -> None:
        print(f"\n=== {title} ===")
        print(
            f"{'strategy':32s} {'ann%':>7s} {'PF':>5s} {'Sharpe':>7s} {'maxDD%':>8s} "
            f"{'worstDay$':>9s} {'trades':>7s} {'blowup':>6s}"
        )
        for r in rows:
            print(
                f"{r['label']:32s} {r['annual_return_pct']:>7.1f} "
                f"{(r['profit_factor'] or 0):>5.2f} {(r['sharpe'] or 0):>7.2f} "
                f"{(r['max_drawdown_pct'] or 0):>8.1f} {(r['worst_day_dollars'] or 0):>9.0f} "
                f"{r['total_trades']:>7d} {str(r['would_blow_up']):>6s}"
            )

    print(
        f"Loaded {meta['n_bars']} bars / {meta['n_days']} days "
        f"({meta['first_day']} -> {meta['last_day']}); dropped {len(bad)} corrupt"
    )
    _digest("NAIVE (signal exit only, no stop)", summary)
    _digest("RISK-MANAGED (0.3% stop / 0.6% target)", risk_managed)
    print(f"\nBest risk-managed strategy: {best_label} (survives={not best['would_blow_up']})")
    print("Per-year P&L ($, 1 contract):", json.dumps(best["per_year"]))
    print("\nContract scaling (leverage lever):")
    for s in scaling:
        print(
            f"  {s['contracts']}c: ann {s['annual_return_pct']:>6.1f}%  "
            f"maxDD {s['max_drawdown_pct']:>6.1f}% (${s['max_drawdown_dollars']:.0f})  "
            f"worstDay ${s['worst_day_dollars']:.0f}  minEq ${s['min_equity']:.0f}  "
            f"blowup={s['would_blow_up']}"
        )


if __name__ == "__main__":
    main()
