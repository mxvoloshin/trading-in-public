"""Out-of-sample validation of the keeper strategy on 2016-2019 (a truly held-out period).

The keeper — gap-and-go + ATR(1.0) stop + a time-of-day exit — was developed and train/test-split
on 2020->2026. This script runs the **exact same strategy with the exact same parameters** (no
re-tuning) on **2016-2019**, a period it has never seen, and puts the numbers side-by-side with the
development window. 2016-2019 is a genuinely different regime mix: 2017's record-low volatility
melt-up, 2018's two corrections (the Feb "volmageddon" spike and the Q4 selloff), and 2019's
recovery — so it is a real stress test, not a friendly one.

If the edge holds here, that is strong evidence it is structural, not curve-fit. If it collapses,
that is exactly what we need to know before trusting it.

Run: uv run python research/mes_intraday/run_oos_2016.py
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
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
# The two windows. OOS is strictly before the development window — no overlap.
OOS = (datetime(2016, 1, 1, tzinfo=UTC), datetime(2020, 1, 1, tzinfo=UTC))
DEV = (datetime(2020, 1, 1, tzinfo=UTC), datetime(2026, 12, 31, tzinfo=UTC))
EXIT_TIMES = [(10, 30), (11, 0), (12, 0), (13, 0), (14, 0), (15, 0)]


def _load(window: tuple[datetime, datetime]):
    df = load_spy_5min(Path(".data"), start=window[0], end=window[1])
    bad = flag_corrupt_days_local(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()
    return df


def _run(df, exit_hm, contracts=1):
    """Same strategy, same params — only the data window changes."""
    sig = gap_and_go(df)  # default gap_thr=0.0015, no re-tuning
    pol = ExitPolicy(label="x", stop_atr=1.0, time_exit=exit_hm)  # same ATR(1.0) stop
    trades = simulate_with_exits(
        df,
        sig.entry_long,
        sig.entry_short,
        pol,
        contracts=contracts,
        commission_scenario=COMM,
        slippage_scenario=SLIP,
    )
    return compute_metrics(
        df,
        trades,
        label="x",
        contracts=contracts,
        commission_scenario=COMM,
        slippage_scenario=SLIP,
    )


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    oos, dev = _load(OOS), _load(DEV)
    oos_days = sorted(set(oos["date"]))
    dev_days = sorted(set(dev["date"]))
    margin = INTRADAY_MARGIN_PER_CONTRACT

    rows = []
    for hm in EXIT_TIMES:
        m_oos = _run(oos, hm)
        m_dev = _run(dev, hm)
        rows.append(
            {
                "exit": f"{hm[0]:02d}:{hm[1]:02d}",
                "oos_annual_pct": m_oos.annual_return_pct,
                "oos_sharpe": m_oos.sharpe,
                "oos_maxdd_pct": m_oos.max_drawdown_pct,
                "oos_min_equity": m_oos.min_equity,
                "oos_survives": m_oos.min_equity >= margin,
                "oos_pf": m_oos.profit_factor,
                "oos_trades": m_oos.total_trades,
                "oos_per_year": m_oos.per_year,
                "dev_annual_pct": m_dev.annual_return_pct,
                "dev_sharpe": m_dev.sharpe,
                "dev_maxdd_pct": m_dev.max_drawdown_pct,
            }
        )

    out = {
        "meta": {
            "oos_window": f"{oos_days[0]} -> {oos_days[-1]} ({len(oos_days)} days)",
            "dev_window": f"{dev_days[0]} -> {dev_days[-1]} ({len(dev_days)} days)",
            "note": "same strategy + params on both; OOS never used in development",
        },
        "rows": rows,
    }
    (RESULTS_DIR / "mes_oos_2016.json").write_text(json.dumps(out, indent=2, default=str))

    print(f"OOS window : {out['meta']['oos_window']}")
    print(f"DEV window : {out['meta']['dev_window']}")
    print("\ngap-and-go + ATR(1.0) stop + time exit — SAME PARAMS, 1 contract on $2,000")
    print(f"\n{'exit':6s} | {'OOS 2016-19':^34s} | {'DEV 2020-26':^18s}")
    print(
        f"{'':6s} | {'ann%':>6s} {'Sharpe':>7s} {'maxDD%':>7s} {'minEq$':>7s} {'surv':>5s} "
        f"| {'ann%':>6s} {'Sharpe':>7s} {'maxDD%':>6s}"
    )
    for r in rows:
        print(
            f"{r['exit']:6s} | {r['oos_annual_pct']:>6.1f} {(r['oos_sharpe'] or 0):>7.2f} "
            f"{(r['oos_maxdd_pct'] or 0):>7.1f} {r['oos_min_equity']:>7.0f} "
            f"{str(r['oos_survives'])[0]:>5s} | {r['dev_annual_pct']:>6.1f} "
            f"{(r['dev_sharpe'] or 0):>7.2f} {(r['dev_maxdd_pct'] or 0):>6.1f}"
        )

    print("\nOOS per-year P&L ($, 1 contract) by exit time:")
    for r in rows:
        print(f"  {r['exit']}: {json.dumps({k: round(v) for k, v in r['oos_per_year'].items()})}")


if __name__ == "__main__":
    main()
