"""Render the account-sizing headline for the keeper strategy on a $5,000 account.

Panel 1 — account equity paths on $5,000 for the three sensible configs (1c conservative,
1c best-exit, 2c best-exit), with the maintenance-margin "ruin line" for each so you can see
which drawdowns stay solvent.
Panel 2 — dollars earned by (account balance x contract count) for the best exit, colored by
whether that combination survives its maintenance margin (green = survives, grey = margin call).

Run: uv run python research/mes_intraday/make_sizing_chart.py
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
from research.mes_intraday.lib import (  # noqa: E402
    INTRADAY_MARGIN_PER_CONTRACT,
    MARKET_TZ,
    flag_corrupt_days_local,
)
from research.mes_intraday.novel import gap_and_go  # noqa: E402

CHARTS_DIR = Path("research/charts")
ACCT = 5000.0


def _equity(df: pd.DataFrame, trades: list, init_cash: float) -> pd.Series:
    daily = pd.Series(0.0, index=pd.Index(sorted(set(df["date"]))))
    for t in trades:
        daily.loc[t.exit_ts.tz_convert(MARKET_TZ).date()] += t.pnl
    return init_cash + daily.cumsum()


def main() -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    df = load_spy_5min(Path(".data"))
    bad = flag_corrupt_days_local(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()
    sig = gap_and_go(df)

    def run(exit_hm, contracts):
        pol = ExitPolicy(label="x", stop_atr=1.0, time_exit=exit_hm)
        return simulate_with_exits(
            df,
            sig.entry_long,
            sig.entry_short,
            pol,
            contracts=contracts,
            commission_scenario="mid",
            slippage_scenario="one",
        )

    e_1c_cons = _equity(df, run((10, 30), 1), ACCT)
    e_1c_best = _equity(df, run((13, 0), 1), ACCT)
    e_2c_best = _equity(df, run((13, 0), 2), ACCT)
    x = pd.to_datetime(pd.Index(e_1c_cons.index))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8.6), gridspec_kw={"height_ratios": [2, 1]})

    ax1.plot(
        x,
        e_1c_cons.to_numpy(),
        lw=1.3,
        color="#27ae60",
        label=r"1 contract, 10:30 exit (conservative): +\$2,981 → \$7,981",
    )
    ax1.plot(
        x,
        e_1c_best.to_numpy(),
        lw=1.3,
        color="#2980b9",
        label=r"1 contract, 13:00 exit (survivable on \$5k): +\$6,075 → \$11,075",
    )
    ax1.plot(
        x,
        e_2c_best.to_numpy(),
        lw=1.5,
        color="#8e44ad",
        label=r"2 contracts, 13:00 exit (aggressive, survivable): +\$12,150 → \$17,150",
    )
    ax1.axhline(ACCT, color="#7f8c8d", ls="--", lw=0.8, label=r"starting equity \$5,000")
    ax1.axhline(
        INTRADAY_MARGIN_PER_CONTRACT, color="#2980b9", ls=":", lw=0.9, label=r"1c margin \$1,400"
    )
    margin_2c = 2 * INTRADAY_MARGIN_PER_CONTRACT
    ax1.axhline(margin_2c, color="#8e44ad", ls=":", lw=0.9, label=r"2c margin \$2,800")
    ax1.set_title(
        "Keeper strategy on a \\$5,000 account — gap-and-go + ATR stop, MES, 2020→2026\n"
        "\\$5k survives the higher-return exit AND a 2nd contract (both margin-called on \\$2k)",
        fontsize=11,
    )
    ax1.set_ylabel("Account equity ($)")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, alpha=0.25)

    # Panel 2: dollars earned by account x contracts (best 13:00 exit), survivability-colored.
    combos = [(2000, 1), (5000, 1), (5000, 2), (5000, 3), (10000, 2), (10000, 3), (10000, 4)]
    labels, earned, colors = [], [], []
    for acct, c in combos:
        margin = INTRADAY_MARGIN_PER_CONTRACT * c
        if margin > acct:
            continue
        eq = _equity(df, run((13, 0), c), acct)
        pnl = eq.iloc[-1] - acct
        survives = eq.min() >= margin
        labels.append(f"${acct / 1000:.0f}k\n{c}c")
        earned.append(pnl)
        colors.append("#27ae60" if survives else "#95a5a6")
    bars = ax2.bar(labels, earned, color=colors)
    for b, val in zip(bars, earned, strict=True):
        ax2.text(
            b.get_x() + b.get_width() / 2,
            val,
            rf"\${val / 1000:.1f}k",
            ha="center",
            va="bottom",
            fontsize=8,
        )
    ax2.set_title(
        "Dollars earned by account × contracts (13:00 exit) — "
        "green survives its margin, grey = margin call (don't trade)",
        fontsize=9,
    )
    ax2.set_ylabel(r"\$ earned (6.5 yrs)")
    ax2.grid(True, axis="y", alpha=0.25)

    fig.tight_layout()
    out = CHARTS_DIR / "mes_account_sizing_5k.png"
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
