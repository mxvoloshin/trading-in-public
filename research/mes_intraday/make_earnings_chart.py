"""Full-decade earnings curve (2016→2026) for the gap-and-go keeper — baseline vs the fix.

Plots account equity for 1 MES on a $2,000 start across the whole cache, for both the baseline
(any gap > 0.15%) and the selective fix (gap > 0.5%), with the 2016-2019 out-of-sample window
shaded apart from the 2020-2026 development window and the $1,400 maintenance-margin ruin line
marked. Shows both the earnings journey and why the fix matters (it never breaches margin).

Run: uv run python research/mes_intraday/make_earnings_chart.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from research.lib.data_access import load_spy_5min  # noqa: E402
from research.mes_intraday.exits import ExitPolicy, simulate_with_exits  # noqa: E402
from research.mes_intraday.lib import (  # noqa: E402
    INIT_CASH,
    INTRADAY_MARGIN_PER_CONTRACT,
    MARKET_TZ,
    flag_corrupt_days_local,
)
from research.mes_intraday.novel import gap_and_go  # noqa: E402

CHARTS_DIR = Path("research/charts")
SPLIT = date(2020, 1, 1)
POLICY = ExitPolicy(label="x", stop_atr=1.0, time_exit=(13, 0))


def _equity(df, gap_thr):
    sig = gap_and_go(df, gap_thr=gap_thr)
    trades = simulate_with_exits(
        df,
        sig.entry_long,
        sig.entry_short,
        POLICY,
        contracts=1,
        commission_scenario="mid",
        slippage_scenario="one",
    )
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

    eq_base = _equity(df, 0.0015)
    eq_fix = _equity(df, 0.005)
    x = pd.to_datetime(pd.Index(eq_base.index))
    split_ts = pd.Timestamp(SPLIT)

    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(
        x,
        eq_base.to_numpy(),
        lw=1.2,
        color="#c0392b",
        label=f"baseline gap>0.15%  (end \\${eq_base.iloc[-1]:,.0f}, dips below margin)",
    )
    ax.plot(
        x,
        eq_fix.to_numpy(),
        lw=1.6,
        color="#1e8449",
        label=f"fix: gap>0.5%  (end \\${eq_fix.iloc[-1]:,.0f}, stays solvent)",
    )
    ax.axhline(INIT_CASH, color="#7f8c8d", ls="--", lw=0.8, label=r"start \$2,000")
    ax.axhline(
        INTRADAY_MARGIN_PER_CONTRACT,
        color="#c0392b",
        ls=":",
        lw=0.9,
        label=r"\$1,400 maintenance margin (ruin line)",
    )

    ax.axvspan(x.min(), split_ts, color="#e74c3c", alpha=0.06)
    ax.axvspan(split_ts, x.max(), color="#27ae60", alpha=0.06)
    ax.axvline(split_ts, color="#555", ls=":", lw=1.0)
    ax.text(
        pd.Timestamp("2018-01-01"),
        eq_fix.max() * 0.58,
        "2016-2019\nout-of-sample",
        fontsize=9,
        ha="center",
        color="#c0392b",
        weight="bold",
    )
    ax.text(
        pd.Timestamp("2023-06-01"),
        eq_fix.max() * 0.5,
        "2020-2026\ndevelopment",
        fontsize=9,
        ha="center",
        color="#1e8449",
        weight="bold",
    )

    ax.set_title(
        "MES gap-and-go earnings, 1 contract on \\$2,000, 2016→2026\n"
        "Selective (gap>0.5%) stays solvent; baseline overtrades into the margin line",
        fontsize=11,
    )
    ax.set_ylabel(r"Account equity (\$)")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.25)

    fig.tight_layout()
    out = CHARTS_DIR / "mes_earnings_2016_2026.png"
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")
    print(f"baseline end ${eq_base.iloc[-1]:,.0f} (min ${eq_base.min():,.0f})")
    print(f"fix      end ${eq_fix.iloc[-1]:,.0f} (min ${eq_fix.min():,.0f})")


if __name__ == "__main__":
    main()
