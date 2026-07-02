"""Run all intraday SPY hypotheses, cost sensitivity, and train/test validation.

Pipeline:
1. Load clean SPY 5-min bars (corrupt segment dropped).
2. Baseline benchmark (intraday buy-open/sell-close).
3. Each hypothesis at the primary cost scenario (tiered_mid + full_spread).
4. Cost & slippage sensitivity grid for survivors.
5. Chronological train/test split + a simple walk-forward for the best candidate.

Writes:
- research/results/experiments.json  (all runs, machine-readable)
- research/results/experiments.csv   (flat table)

Run:
    uv run python research/run_experiments.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.lib import strategies as strat  # noqa: E402
from research.lib.backtest import (  # noqa: E402
    COMMISSION_RATES,
    SLIPPAGE_CENTS,
    run_intraday_backtest,
)
from research.lib.data_access import (  # noqa: E402
    chronological_split,
    load_clean_spy_5min,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".data"
RESULTS_DIR = REPO_ROOT / "research" / "results"

# Hypotheses: label -> (signal function, kwargs). Kept to simple, explainable
# rules with round-number parameters (no fine-tuning), per the research rules.
HYPOTHESES: dict[str, tuple] = {
    "H0_buy_open_sell_close": (strat.buy_open_sell_close_signals, {}),
    "H1_orb_breakout": (strat.orb_breakout_signals, {"opening_range_bars": 6}),
    "H2_orb_fade": (strat.orb_fade_signals, {"opening_range_bars": 6}),
    "H3_rsi_meanrev": (
        strat.rsi_meanrev_signals,
        {"window": 14, "lower": 30.0, "exit_level": 55.0},
    ),
    "H4_zscore_meanrev": (
        strat.zscore_meanrev_signals,
        {"window": 20, "entry_z": -1.5, "exit_z": 0.0},
    ),
    "H5_ma_cross": (strat.ma_cross_intraday_signals, {"fast": 9, "slow": 21}),
}

PRIMARY_COMMISSION = "tiered_mid"
PRIMARY_SLIPPAGE = "full_spread"


def run_all(df: pd.DataFrame) -> list[dict]:
    """Every hypothesis at the primary cost scenario."""
    rows: list[dict] = []
    for label, (fn, kwargs) in HYPOTHESES.items():
        sig = fn(df, **kwargs)
        m = run_intraday_backtest(
            df,
            sig,
            label=label,
            commission_scenario=PRIMARY_COMMISSION,
            slippage_scenario=PRIMARY_SLIPPAGE,
        )
        rows.append(m.to_row())
    return rows


def cost_grid(df: pd.DataFrame, label: str) -> list[dict]:
    """Full commission x slippage grid for one strategy (cost sensitivity)."""
    fn, kwargs = HYPOTHESES[label]
    sig = fn(df, **kwargs)
    rows: list[dict] = []
    for comm in COMMISSION_RATES:
        for slip in SLIPPAGE_CENTS:
            m = run_intraday_backtest(
                df,
                sig,
                label=f"{label}|{comm}|{slip}",
                commission_scenario=comm,
                slippage_scenario=slip,
            )
            rows.append(m.to_row())
    return rows


def train_test(df: pd.DataFrame, label: str) -> list[dict]:
    """Chronological train/test split for one strategy at the primary scenario."""
    fn, kwargs = HYPOTHESES[label]
    split = chronological_split(df, train_frac=0.7)
    rows: list[dict] = []
    for name, frame in (("train", split.train), ("test", split.test)):
        sig = fn(frame, **kwargs)
        m = run_intraday_backtest(
            frame,
            sig,
            label=f"{label}|{name}",
            commission_scenario=PRIMARY_COMMISSION,
            slippage_scenario=PRIMARY_SLIPPAGE,
        )
        row = m.to_row()
        row["split"] = name
        row["split_date"] = str(split.split_date)
        rows.append(row)
    return rows


def walk_forward(df: pd.DataFrame, label: str, *, n_folds: int = 4) -> list[dict]:
    """Simple expanding-window walk-forward: test on each of N sequential blocks.

    No parameters are re-fit (the rules are fixed), so this is an out-of-sample
    *stability* check: does the edge persist across sequential time blocks, or is
    it driven by one lucky stretch?
    """
    fn, kwargs = HYPOTHESES[label]
    dates = sorted(set(df["date"]))
    fold_size = len(dates) // n_folds
    rows: list[dict] = []
    for i in range(n_folds):
        lo = i * fold_size
        hi = (i + 1) * fold_size if i < n_folds - 1 else len(dates)
        fold_dates = set(dates[lo:hi])
        frame = df[df["date"].isin(fold_dates)]
        sig = fn(frame, **kwargs)
        m = run_intraday_backtest(
            frame,
            sig,
            label=f"{label}|fold{i + 1}",
            commission_scenario=PRIMARY_COMMISSION,
            slippage_scenario=PRIMARY_SLIPPAGE,
        )
        row = m.to_row()
        row["fold"] = i + 1
        row["fold_start"] = str(dates[lo])
        row["fold_end"] = str(dates[hi - 1])
        rows.append(row)
    return rows


def main() -> None:
    df, dropped = load_clean_spy_5min(CACHE_DIR)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    all_runs = run_all(df)

    # Rank survivors by net annualized return at the primary scenario, but we
    # decide promotion in the report using the full picture (not just profit).
    ranked = sorted(
        all_runs,
        key=lambda r: r["annualized_return_pct"] or -999,
        reverse=True,
    )
    # Run cost grid + validation for the top 2 non-benchmark strategies.
    candidates = [r["label"] for r in ranked if not r["label"].startswith("H0")][:2]

    grids = {c: cost_grid(df, c) for c in candidates}
    splits = {c: train_test(df, c) for c in candidates}
    wfs = {c: walk_forward(df, c) for c in candidates}

    payload = {
        "meta": {
            "clean_trade_days": int(df["date"].nunique()),
            "dropped_corrupt_days": [str(d) for d in dropped],
            "primary_commission": PRIMARY_COMMISSION,
            "primary_slippage": PRIMARY_SLIPPAGE,
        },
        "all_runs": all_runs,
        "candidates": candidates,
        "cost_grids": grids,
        "train_test": splits,
        "walk_forward": wfs,
    }
    (RESULTS_DIR / "experiments.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    pd.DataFrame(all_runs).to_csv(RESULTS_DIR / "experiments.csv", index=False)

    # Console summary.
    cols = [
        "label",
        "annualized_return_pct",
        "total_return_pct",
        "gross_return_pct",
        "sharpe",
        "max_drawdown_pct",
        "total_trades",
        "trades_per_month",
        "win_rate_pct",
        "profit_factor",
        "expectancy",
        "avg_hold_minutes",
        "exposure_pct",
    ]
    print("=== Hypotheses @ tiered_mid + full_spread (net of costs) ===")
    print(pd.DataFrame(all_runs)[cols].to_string(index=False))
    print("\ncandidates for cost-grid + validation:", candidates)
    print("wrote", RESULTS_DIR / "experiments.json")


if __name__ == "__main__":
    main()
