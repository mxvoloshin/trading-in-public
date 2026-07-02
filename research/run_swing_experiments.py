"""Swing / multi-timeframe SPY hypotheses: full-cycle vs focus-window, costs, robustness.

Pipeline:
1. Load clean daily bars (2016->2026) and the 2025->2026 focus subperiod.
2. Run every hypothesis on both windows at the primary cost scenario.
3. Cost & slippage sensitivity grid for the survivors.
4. Per-calendar-year walk-forward (does the edge persist across regimes?).
5. Chronological train/test split.
6. Analytic Reg-T 2x leverage projection (with margin-interest drag and a
   margin-call flag), since swing trades escape the PDT rule that capped the
   intraday study.

Writes:
- research/results/swing_experiments.json  (all runs, machine-readable)
- research/results/swing_experiments.csv    (flat full+focus table)

Run:
    uv run python research/run_swing_experiments.py
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from research.lib import swing_strategies as strat  # noqa: E402
from research.lib.swing_backtest import (  # noqa: E402
    COMMISSION_RATES,
    SLIPPAGE_CENTS,
    run_swing_backtest,
)
from research.lib.swing_data import (  # noqa: E402
    chronological_split,
    load_clean_bars,
    restrict_to_period,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / ".data"
RESULTS_DIR = REPO_ROOT / "research" / "results"

FOCUS_START = date(2025, 1, 1)
FOCUS_END = date(2026, 12, 31)
PRIMARY_COMMISSION = "tiered_mid"
PRIMARY_SLIPPAGE = "full_spread"

# Annual margin interest on the borrowed half at 2x (IBKR benchmark ~6%/yr).
MARGIN_INTEREST = 0.06

# label -> (signal fn, kwargs, timeframe). Simple, explainable rules with
# round-number parameters. Daily is the primary timeframe (long history);
# overnight_hold needs an intraday frame.
HYPOTHESES: dict[str, tuple] = {
    "H0_buy_and_hold": (strat.buy_and_hold, {}, "1Day"),
    "H1_sma_trend200": (strat.sma_trend, {"window": 200}, "1Day"),
    "H2_sma_trend50": (strat.sma_trend, {"window": 50}, "1Day"),
    "H3_ma_cross20_100": (strat.ma_cross, {"fast": 20, "slow": 100}, "1Day"),
    "H4_rsi2_meanrev": (strat.rsi2_meanrev, {}, "1Day"),
    "H5_donchian20_10": (strat.donchian_breakout, {"entry_window": 20, "exit_window": 10}, "1Day"),
    "H6_dip_buy3": (strat.dip_buy, {"down_days": 3}, "1Day"),
    "H7_overnight_hold": (strat.overnight_hold, {}, "15Min"),
}

# Cache loaded frames so we don't re-read per hypothesis.
_FRAMES: dict[str, pd.DataFrame] = {}


def _frame(timeframe: str) -> pd.DataFrame:
    if timeframe not in _FRAMES:
        df, _ = load_clean_bars(CACHE_DIR, timeframe=timeframe)
        _FRAMES[timeframe] = df
    return _FRAMES[timeframe]


def _freq_for(timeframe: str) -> str:
    return {"1Day": "D", "1Hour": "1h", "15Min": "15min"}.get(timeframe, "D")


def _run(label: str, window_tag: str, restrict: bool) -> dict:
    fn, kwargs, tf = HYPOTHESES[label]
    df = _frame(tf)
    if restrict:
        df = restrict_to_period(df, start=FOCUS_START, end=FOCUS_END)
    sig = fn(df, **kwargs)
    m = run_swing_backtest(
        df,
        sig,
        label=label,
        timeframe=tf,
        commission_scenario=PRIMARY_COMMISSION,
        slippage_scenario=PRIMARY_SLIPPAGE,
        freq=_freq_for(tf),
    )
    row = m.to_row()
    row["window"] = window_tag
    row.update(_leverage_projection(m))
    return row


def _leverage_projection(m) -> dict:  # type: ignore[no-untyped-def]
    """Analytic 2x Reg-T projection: return/drawdown scale ~linearly, minus borrow.

    A fixed-fraction long book at 2x roughly doubles both return and drawdown; we
    subtract margin interest on the borrowed half. The margin-call flag fires when
    the *underlying* drawdown exceeds 33.3% (equity=50% of notional, 25%
    maintenance), i.e. the 2x position would be liquidated.
    """
    ann = m.annualized_return_pct
    dd = m.max_drawdown_pct
    two_x_ann = None if ann is None else ann * 2 - MARGIN_INTEREST * 100
    two_x_dd = None if dd is None else dd * 2
    return {
        "two_x_ann_return_pct": two_x_ann,
        "two_x_max_drawdown_pct": two_x_dd,
        "two_x_margin_call": bool(dd is not None and abs(dd) > 33.3),
    }


def cost_grid(label: str, restrict: bool) -> list[dict]:
    """Full commission x slippage grid for one strategy on the chosen window."""
    fn, kwargs, tf = HYPOTHESES[label]
    df = _frame(tf)
    if restrict:
        df = restrict_to_period(df, start=FOCUS_START, end=FOCUS_END)
    sig = fn(df, **kwargs)
    rows: list[dict] = []
    for comm in COMMISSION_RATES:
        for slip in SLIPPAGE_CENTS:
            m = run_swing_backtest(
                df,
                sig,
                label=f"{label}|{comm}|{slip}",
                timeframe=tf,
                commission_scenario=comm,
                slippage_scenario=slip,
                freq=_freq_for(tf),
            )
            rows.append(m.to_row())
    return rows


def per_year(label: str) -> list[dict]:
    """Per-calendar-year run (regime-by-regime stability check, fixed rules)."""
    fn, kwargs, tf = HYPOTHESES[label]
    df = _frame(tf)
    rows: list[dict] = []
    for y in range(2016, 2027):
        seg = restrict_to_period(df, start=date(y, 1, 1), end=date(y, 12, 31))
        if seg["date"].nunique() < 40:
            continue
        m = run_swing_backtest(
            seg,
            fn(seg, **kwargs),
            label=f"{label}|{y}",
            timeframe=tf,
            commission_scenario=PRIMARY_COMMISSION,
            slippage_scenario=PRIMARY_SLIPPAGE,
            freq=_freq_for(tf),
        )
        row = m.to_row()
        row["year"] = y
        rows.append(row)
    return rows


def train_test(label: str) -> list[dict]:
    """Chronological 70/30 train/test split on the full history."""
    fn, kwargs, tf = HYPOTHESES[label]
    split = chronological_split(_frame(tf), train_frac=0.7)
    rows: list[dict] = []
    for name, frame in (("train", split.train), ("test", split.test)):
        m = run_swing_backtest(
            frame,
            fn(frame, **kwargs),
            label=f"{label}|{name}",
            timeframe=tf,
            commission_scenario=PRIMARY_COMMISSION,
            slippage_scenario=PRIMARY_SLIPPAGE,
            freq=_freq_for(tf),
        )
        row = m.to_row()
        row["split"] = name
        row["split_date"] = str(split.split_date)
        rows.append(row)
    return rows


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    full_runs = [_run(label, "full_2016_2026", restrict=False) for label in HYPOTHESES]
    focus_runs = [_run(label, "focus_2025_2026", restrict=True) for label in HYPOTHESES]

    # Candidates for the deep dives: everything except the benchmark and the
    # intraday overnight hold (which has no decade of history).
    candidates = ["H1_sma_trend200", "H2_sma_trend50", "H4_rsi2_meanrev", "H5_donchian20_10"]

    payload = {
        "meta": {
            "primary_commission": PRIMARY_COMMISSION,
            "primary_slippage": PRIMARY_SLIPPAGE,
            "margin_interest_annual": MARGIN_INTEREST,
            "focus_window": [str(FOCUS_START), str(FOCUS_END)],
        },
        "full_runs": full_runs,
        "focus_runs": focus_runs,
        "cost_grids_full": {c: cost_grid(c, restrict=False) for c in candidates},
        "cost_grids_focus": {c: cost_grid(c, restrict=True) for c in candidates},
        "per_year": {c: per_year(c) for c in ["H0_buy_and_hold", *candidates]},
        "train_test": {c: train_test(c) for c in candidates},
    }
    (RESULTS_DIR / "swing_experiments.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8"
    )
    flat = pd.DataFrame(full_runs + focus_runs)
    flat.to_csv(RESULTS_DIR / "swing_experiments.csv", index=False)

    cols = [
        "label",
        "window",
        "annualized_return_pct",
        "sharpe",
        "max_drawdown_pct",
        "profit_factor",
        "total_trades",
        "exposure_pct",
        "two_x_ann_return_pct",
        "two_x_max_drawdown_pct",
        "two_x_margin_call",
    ]
    pd.set_option("display.width", 200)
    print("=== FULL 2016-2026 (net, tiered_mid + full_spread) ===")
    print(pd.DataFrame(full_runs)[cols].to_string(index=False))
    print("\n=== FOCUS 2025-2026 ===")
    print(pd.DataFrame(focus_runs)[cols].to_string(index=False))
    print("\nwrote", RESULTS_DIR / "swing_experiments.json")


if __name__ == "__main__":
    main()
