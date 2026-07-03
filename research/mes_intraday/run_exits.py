"""Exit-strategy study: hold the best *entries* fixed, benchmark the exit *menu*.

For each of the strategies that showed any edge — ORB (long+short), gap-and-go, and the
trend-day ride — we run all ten exit policies from ``exits.exit_menu`` through the same MES
dollar accounting and compare return, Sharpe, drawdown, worst day, and (for the best exit per
entry) the chronological train/test split. The question: can a better *exit* materially improve
results, or reach a robust, survivable 20%, where better entries could not?

Run: uv run python research/mes_intraday/run_exits.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from research.lib.data_access import load_spy_5min  # noqa: E402
from research.mes_intraday.exits import ExitPolicy, exit_menu, simulate_with_exits  # noqa: E402
from research.mes_intraday.lib import (  # noqa: E402
    INTRADAY_MARGIN_PER_CONTRACT,
    compute_metrics,
    flag_corrupt_days_local,
    orb_ls,
)
from research.mes_intraday.novel import gap_and_go, trend_day_ride  # noqa: E402

RESULTS_DIR = Path("research/results")
COMM, SLIP = "mid", "one"

# The entry signals under study (each returns LSSignals; we use only its entries).
ENTRIES = {
    "ORB (long+short)": orb_ls,
    "gap-and-go": gap_and_go,
    "trend-day ride": trend_day_ride,
}


def _metrics(df, label, entry_long, entry_short, policy):
    trades = simulate_with_exits(
        df, entry_long, entry_short, policy, commission_scenario=COMM, slippage_scenario=SLIP
    )
    m = compute_metrics(
        df, trades, label=label, contracts=1, commission_scenario=COMM, slippage_scenario=SLIP
    )
    return m


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df = load_spy_5min(Path(".data"))
    bad = flag_corrupt_days_local(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()
    days = sorted(set(df["date"]))
    cut = days[int(len(days) * 0.70)]
    train, test = df[df["date"] < cut].copy(), df[df["date"] >= cut].copy()

    menu = exit_menu()
    out: dict = {"meta": {"n_days": len(days), "split_date": str(cut)}, "by_entry": {}}

    for entry_label, entry_fn in ENTRIES.items():
        sig = entry_fn(df)
        rows = []
        for pol in menu:
            m = _metrics(df, f"{entry_label} | {pol.label}", sig.entry_long, sig.entry_short, pol)
            rows.append({**m.to_row(), "exit": pol.label, "per_year": m.per_year})
        # Best exit for this entry = highest annual return among the survivable-ish
        # (rank by return, but surface drawdown so we can judge).
        best = max(rows, key=lambda r: r["annual_return_pct"])
        # Train/test the best exit.
        pol = next(p for p in menu if p.label == best["exit"])
        sig_tr, sig_te = entry_fn(train), entry_fn(test)
        m_tr = _metrics(train, "train", sig_tr.entry_long, sig_tr.entry_short, pol)
        m_te = _metrics(test, "test", sig_te.entry_long, sig_te.entry_short, pol)
        out["by_entry"][entry_label] = {
            "exits": rows,
            "best_exit": best["exit"],
            "train_annual_pct": m_tr.annual_return_pct,
            "train_pf": m_tr.profit_factor,
            "test_annual_pct": m_te.annual_return_pct,
            "test_pf": m_te.profit_factor,
        }

    # --- Headline: gap-and-go time-of-day exit sweep + strict survivability ----
    # Strict survivability = the account's minimum equity never drops below the
    # maintenance margin needed to keep holding one contract (else a margin call).
    margin = INTRADAY_MARGIN_PER_CONTRACT
    gg = gap_and_go(df)
    gg_tr, gg_te = gap_and_go(train), gap_and_go(test)
    sweep = []
    for hm in [(10, 30), (11, 0), (11, 30), (12, 0), (13, 0), (13, 30), (14, 0), (15, 0)]:
        pol = ExitPolicy(label=f"exit {hm[0]:02d}:{hm[1]:02d}", stop_atr=1.0, time_exit=hm)
        m = _metrics(df, "gg", gg.entry_long, gg.entry_short, pol)
        m_tr = _metrics(train, "gg", gg_tr.entry_long, gg_tr.entry_short, pol)
        m_te = _metrics(test, "gg", gg_te.entry_long, gg_te.entry_short, pol)
        sweep.append(
            {
                "exit_time": f"{hm[0]:02d}:{hm[1]:02d}",
                "annual_return_pct": m.annual_return_pct,
                "sharpe": m.sharpe,
                "max_drawdown_pct": m.max_drawdown_pct,
                "min_equity": m.min_equity,
                "survives_margin": m.min_equity >= margin,
                "train_annual_pct": m_tr.annual_return_pct,
                "test_annual_pct": m_te.annual_return_pct,
                "per_year": m.per_year,
            }
        )
    out["gap_and_go_time_exit_sweep"] = {"maintenance_margin": margin, "rows": sweep}

    (RESULTS_DIR / "mes_exits_summary.json").write_text(json.dumps(out, indent=2, default=str))

    for entry_label, block in out["by_entry"].items():
        print(f"\n=== ENTRY: {entry_label} — exit menu (1c, mid/one) ===")
        print(
            f"{'exit':34s} {'ann%':>7s} {'PF':>5s} {'Sharpe':>7s} {'maxDD%':>8s} "
            f"{'worst$':>7s} {'trades':>6s} {'blow':>4s}"
        )
        for r in block["exits"]:
            print(
                f"{r['exit']:34s} {r['annual_return_pct']:>7.1f} {(r['profit_factor'] or 0):>5.2f} "
                f"{(r['sharpe'] or 0):>7.2f} {(r['max_drawdown_pct'] or 0):>8.1f} "
                f"{(r['worst_day_dollars'] or 0):>7.0f} {r['total_trades']:>6d} "
                f"{str(r['would_blow_up'])[0]:>4s}"
            )
        print(
            f"  best exit: {block['best_exit']}  |  "
            f"train {block['train_annual_pct']:.1f}% (PF {block['train_pf']})  "
            f"test {block['test_annual_pct']:.1f}% (PF {block['test_pf']})"
        )

    sw = out["gap_and_go_time_exit_sweep"]
    print("\n=== HEADLINE: gap-and-go time-of-day exit sweep (ATR 1.0 stop, 1c) ===")
    print(f"maintenance margin to hold 1 MES = ${sw['maintenance_margin']:.0f} (account $2,000)")
    print(
        f"{'exit':8s} {'ann%':>7s} {'Sharpe':>7s} {'maxDD%':>8s} {'minEq$':>7s} {'survive':>8s} "
        f"{'train%':>7s} {'test%':>7s}"
    )
    for r in sw["rows"]:
        surv = str(r["survives_margin"])
        print(
            f"{r['exit_time']:8s} {r['annual_return_pct']:>7.1f} {(r['sharpe'] or 0):>7.2f} "
            f"{(r['max_drawdown_pct'] or 0):>8.1f} {r['min_equity']:>7.0f} "
            f"{surv:>8s} {r['train_annual_pct']:>7.1f} {r['test_annual_pct']:>7.1f}"
        )


if __name__ == "__main__":
    main()
