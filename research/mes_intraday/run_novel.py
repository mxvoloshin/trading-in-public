"""Run the *novel* MES intraday mechanisms and compare them to the earlier baselines.

Same rigor as run_mes.py (MES economics, long+short, flat-by-EOD, 1 contract on $2,000,
train/test split, ruin check) but over the structurally-new strategies in novel.py that
use cross-session / day-type / volume information the prior single-signal rules ignored.

Run: uv run python research/mes_intraday/run_novel.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from research.lib.data_access import load_spy_5min  # noqa: E402
from research.mes_intraday.lib import (  # noqa: E402
    compute_metrics,
    flag_corrupt_days_local,
    simulate_mes,
)
from research.mes_intraday.novel import NOVEL_STRATEGIES  # noqa: E402

RESULTS_DIR = Path("research/results")
COMM, SLIP = "mid", "one"


def _row(df, label, trades, contracts=1) -> dict:
    m = compute_metrics(
        df,
        trades,
        label=label,
        contracts=contracts,
        commission_scenario=COMM,
        slippage_scenario=SLIP,
    )
    return {**m.to_row(), "per_year": m.per_year}


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df = load_spy_5min(Path(".data"))
    bad = flag_corrupt_days_local(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()
    days = sorted(set(df["date"]))

    naive, managed = [], []
    for label, fn in NOVEL_STRATEGIES.items():
        sig = fn(df)
        naive.append(
            _row(df, label, simulate_mes(df, sig, commission_scenario=COMM, slippage_scenario=SLIP))
        )
        managed.append(
            _row(
                df,
                label,
                simulate_mes(
                    df,
                    sig,
                    commission_scenario=COMM,
                    slippage_scenario=SLIP,
                    stop_frac=0.003,
                    target_frac=0.006,
                ),
            )
        )

    # Chronological 70/30 train/test on the naive variant.
    cut = days[int(len(days) * 0.70)]
    train = df[df["date"] < cut].copy()
    test = df[df["date"] >= cut].copy()
    splits = []
    for label, fn in NOVEL_STRATEGIES.items():
        row = {"label": label, "split_date": str(cut)}
        for name, part in (("train", train), ("test", test)):
            m = compute_metrics(
                part,
                simulate_mes(part, fn(part), commission_scenario=COMM, slippage_scenario=SLIP),
                label=label,
                contracts=1,
                commission_scenario=COMM,
                slippage_scenario=SLIP,
            )
            row[f"{name}_annual_pct"] = m.annual_return_pct
            row[f"{name}_pf"] = m.profit_factor
            row[f"{name}_maxdd_pct"] = m.max_drawdown_pct
        splits.append(row)

    out = {
        "meta": {"n_days": len(days), "first_day": str(days[0]), "last_day": str(days[-1])},
        "naive": naive,
        "risk_managed": managed,
        "train_test": splits,
    }
    (RESULTS_DIR / "mes_novel_summary.json").write_text(json.dumps(out, indent=2, default=str))

    def _digest(title, rows):
        print(f"\n=== {title} ===")
        print(
            f"{'strategy':38s} {'ann%':>7s} {'PF':>5s} {'Sharpe':>7s} {'maxDD%':>8s} "
            f"{'worst$':>7s} {'trades':>6s} {'blow':>5s}"
        )
        for r in rows:
            blow = str(r["would_blow_up"])[0]
            pf = r["profit_factor"] or 0
            print(
                f"{r['label']:38s} {r['annual_return_pct']:>7.1f} {pf:>5.2f} "
                f"{(r['sharpe'] or 0):>7.2f} {(r['max_drawdown_pct'] or 0):>8.1f} "
                f"{(r['worst_day_dollars'] or 0):>7.0f} {r['total_trades']:>6d} {blow:>5s}"
            )

    print(f"Loaded {len(days)} days ({days[0]} -> {days[-1]})")
    _digest("NOVEL — naive (signal/level exit)", naive)
    _digest("NOVEL — risk-managed (0.3% stop / 0.6% tgt)", managed)
    print("\n=== NOVEL — train/test (naive, 1c) ===")
    for r in splits:
        print(
            f"  {r['label']:38s} train {r['train_annual_pct']:>7.1f}% (PF {r['train_pf']})  "
            f"test {r['test_annual_pct']:>7.1f}% (PF {r['test_pf']})"
        )


if __name__ == "__main__":
    main()
