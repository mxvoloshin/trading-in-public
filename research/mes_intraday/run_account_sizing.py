"""Account-size sensitivity for the keeper strategy (gap-and-go + ATR stop + time exit).

The dollar P&L of a fixed-contract futures strategy does not depend on account size — but the
account size decides (a) whether the drawdown survives the maintenance margin and (b) how many
contracts you can safely hold. This script sweeps account balances x contract counts x the two
headline exit times and reports, for each, the dollars earned, the ending equity, the annualized
return on that balance, and a strict survivability check (min account equity must stay above the
maintenance margin for the held contracts, else a margin call ends the run).

Run: uv run python research/mes_intraday/run_account_sizing.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from research.lib.data_access import load_spy_5min  # noqa: E402
from research.mes_intraday.exits import ExitPolicy, simulate_with_exits  # noqa: E402
from research.mes_intraday.lib import (  # noqa: E402
    INTRADAY_MARGIN_PER_CONTRACT,
    compute_metrics,
    flag_corrupt_days_local,
)
from research.mes_intraday.novel import gap_and_go  # noqa: E402

RESULTS_DIR = Path("research/results")
COMM, SLIP = "mid", "one"
ACCOUNTS = [2000.0, 5000.0, 10000.0]
CONTRACTS = [1, 2, 3, 4]
EXITS = {"10:30 conservative": (10, 30), "13:00 best": (13, 0)}


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    df = load_spy_5min(Path(".data"))
    bad = flag_corrupt_days_local(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()
    days = sorted(set(df["date"]))
    cut = days[int(len(days) * 0.70)]
    tr, te = df[df["date"] < cut].copy(), df[df["date"] >= cut].copy()
    sig, sig_tr, sig_te = gap_and_go(df), gap_and_go(tr), gap_and_go(te)

    def run(frame, s, exit_hm, contracts, acct):
        pol = ExitPolicy(label="x", stop_atr=1.0, time_exit=exit_hm)
        trades = simulate_with_exits(
            frame,
            s.entry_long,
            s.entry_short,
            pol,
            contracts=contracts,
            commission_scenario=COMM,
            slippage_scenario=SLIP,
        )
        return compute_metrics(
            frame,
            trades,
            label="x",
            contracts=contracts,
            commission_scenario=COMM,
            slippage_scenario=SLIP,
            init_cash=acct,
        )

    rows = []
    for exit_name, hm in EXITS.items():
        for acct in ACCOUNTS:
            for c in CONTRACTS:
                margin = INTRADAY_MARGIN_PER_CONTRACT * c
                if margin > acct:
                    continue  # can't even open this many contracts on this balance
                m = run(df, sig, hm, c, acct)
                m_tr = run(tr, sig_tr, hm, c, acct)
                m_te = run(te, sig_te, hm, c, acct)
                rows.append(
                    {
                        "exit": exit_name,
                        "account": acct,
                        "contracts": c,
                        "dollars_earned": m.total_pnl,
                        "ending_equity": m.ending_equity,
                        "annual_return_pct": m.annual_return_pct,
                        "cagr_pct": m.cagr_pct,
                        "sharpe": m.sharpe,
                        "max_drawdown_pct": m.max_drawdown_pct,
                        "min_equity": m.min_equity,
                        "margin_required": margin,
                        "survives_margin": m.min_equity >= margin,
                        "train_annual_pct": m_tr.annual_return_pct,
                        "test_annual_pct": m_te.annual_return_pct,
                        "per_year": m.per_year,
                    }
                )

    span_years = (df.index.max() - df.index.min()).days / 365.25
    out = {
        "meta": {"span_years": round(span_years, 2), "first": str(days[0]), "last": str(days[-1])},
        "rows": rows,
    }
    (RESULTS_DIR / "mes_account_sizing.json").write_text(json.dumps(out, indent=2, default=str))

    print(f"gap-and-go + ATR(1.0) stop | {days[0]} -> {days[-1]} ({span_years:.1f} yrs)")
    print("(dollars earned are fixed-contract P&L — independent of the account balance)\n")
    hdr = (
        f"{'exit':18s} {'acct$':>7s} {'size':>4s} {'earned$':>9s} {'end$':>9s} "
        f"{'ann%':>6s} {'CAGR%':>6s} {'maxDD%':>7s} {'minEq$':>7s} {'survive':>8s} {'tr/te%':>13s}"
    )
    print(hdr)
    for r in rows:
        cagr = r["cagr_pct"] or 0
        print(
            f"{r['exit']:18s} {r['account']:>7.0f} {r['contracts']:>4d} "
            f"{r['dollars_earned']:>9,.0f} {r['ending_equity']:>9,.0f} "
            f"{r['annual_return_pct']:>6.1f} {cagr:>6.1f} {r['max_drawdown_pct']:>7.1f} "
            f"{r['min_equity']:>7.0f} {str(r['survives_margin']):>8s} "
            f"{r['train_annual_pct']:>5.0f}/{r['test_annual_pct']:<5.0f}"
        )


if __name__ == "__main__":
    main()
