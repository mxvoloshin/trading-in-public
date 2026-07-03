"""Render the exit-study headline: how the *exit* transforms the same gap-and-go entries.

Panel 1 — account equity for the same gap-and-go entries under three exits: EOD hold (the
old default), a fixed 0.3%/0.6% stop, and the ATR-stop + midday time-exit. Same entries,
wildly different outcomes — the point of the whole study.
Panel 2 — the exit-time plateau: annualized return vs exit time, with the maintenance-margin
survivability band shaded, showing it is a broad ridge (not a lucky single point).

Run: uv run python research/mes_intraday/make_exit_chart.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from research.lib.data_access import load_spy_5min  # noqa: E402
from research.mes_intraday.exits import ExitPolicy, simulate_with_exits  # noqa: E402
from research.mes_intraday.lib import INIT_CASH, MARKET_TZ, flag_corrupt_days_local  # noqa: E402
from research.mes_intraday.novel import gap_and_go  # noqa: E402

CHARTS_DIR = Path("research/charts")


def _equity(df: pd.DataFrame, trades: list) -> pd.Series:
    daily = pd.Series(0.0, index=pd.Index(sorted(set(df["date"]))))
    for t in trades:
        daily.loc[t.exit_ts.tz_convert(MARKET_TZ).date()] += t.pnl
    return INIT_CASH + daily.cumsum()


def main() -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    df = load_spy_5min(Path(".data"))
    bad = flag_corrupt_days_local(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()
    sig = gap_and_go(df)

    def run(pol: ExitPolicy) -> list:
        return simulate_with_exits(
            df,
            sig.entry_long,
            sig.entry_short,
            pol,
            commission_scenario="mid",
            slippage_scenario="one",
        )

    eod = run(ExitPolicy(label="eod"))  # no stop, EOD hold
    fixed = run(ExitPolicy(label="fx", stop_frac=0.003, target_frac=0.006))
    timed = run(ExitPolicy(label="tm", stop_atr=1.0, time_exit=(13, 0)))
    survive = run(ExitPolicy(label="sv", stop_atr=1.0, time_exit=(10, 30)))

    eq_eod, eq_fx, eq_tm, eq_sv = (_equity(df, t) for t in (eod, fixed, timed, survive))
    x = pd.to_datetime(pd.Index(eq_eod.index))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8.5), gridspec_kw={"height_ratios": [2, 1]})

    ax1.plot(
        x,
        eq_eod.to_numpy(),
        lw=1.2,
        color="#c0392b",
        label="EOD hold, no stop (old default): -11%/yr",
    )
    ax1.plot(x, eq_fx.to_numpy(), lw=1.2, color="#e67e22", label="fixed 0.3%/0.6% stop: +8%/yr")
    ax1.plot(
        x,
        eq_sv.to_numpy(),
        lw=1.4,
        color="#27ae60",
        label="ATR stop + 10:30 exit (survivable): +23%/yr",
    )
    ax1.plot(
        x, eq_tm.to_numpy(), lw=1.4, color="#2980b9", label="ATR stop + 13:00 exit (best): +47%/yr"
    )
    ax1.axhline(INIT_CASH, color="#7f8c8d", ls="--", lw=0.8)
    ax1.axhline(
        1400, color="#c0392b", ls=":", lw=0.9, label="$1,400 maintenance margin (ruin line)"
    )
    ax1.set_title(
        "Same gap-and-go ENTRIES, four EXITS — the exit is what changes the outcome\n"
        "MES, 1 contract on $2,000, 2020→2026",
        fontsize=11,
    )
    ax1.set_ylabel("Account equity ($)")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, alpha=0.25)

    # Panel 2: exit-time plateau (recompute a quick sweep).
    times = [(10, 30), (11, 0), (11, 30), (12, 0), (13, 0), (13, 30), (14, 0), (15, 0)]
    anns, labels, min_eqs = [], [], []
    for hm in times:
        eq = _equity(df, run(ExitPolicy(label="s", stop_atr=1.0, time_exit=hm)))
        pnl = eq.iloc[-1] - INIT_CASH
        years = (x.max() - x.min()).days / 365.25
        anns.append(pnl / INIT_CASH / years * 100)
        min_eqs.append(eq.min())
        labels.append(f"{hm[0]:02d}:{hm[1]:02d}")
    colors = ["#27ae60" if me >= 1400 else "#2980b9" for me in min_eqs]
    ax2.bar(labels, anns, color=colors)
    ax2.axhline(20, color="#7f8c8d", ls="--", lw=0.9, label="20% target")
    ax2.set_title(
        "Exit-time plateau: annualized return by exit time (green = survives $2k margin, "
        "blue = needs a bigger account)",
        fontsize=9,
    )
    ax2.set_ylabel("Annualized %")
    ax2.set_xlabel("Time-of-day exit")
    ax2.legend(loc="upper left", fontsize=8)
    ax2.grid(True, axis="y", alpha=0.25)

    fig.tight_layout()
    out = CHARTS_DIR / "mes_exit_strategy_comparison.png"
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
