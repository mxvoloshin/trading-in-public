"""Render the out-of-sample verdict: one continuous 2016→2026 equity curve for the keeper.

Runs gap-and-go + ATR(1.0) stop + 13:00 exit (the best development-period config, unchanged)
continuously across 2016→2026 and plots account equity, shading the held-out 2016-2019 window
apart from the 2020-2026 development window. The picture is the point: the strategy went nowhere
for four years (the low-vol / whipsaw 2016-2019 regime) and only worked in 2020-2026 — i.e. the
edge is regime-conditional, not a stable all-weather signal.

Run: uv run python research/mes_intraday/make_oos_chart.py
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
from research.mes_intraday.lib import INIT_CASH, MARKET_TZ, flag_corrupt_days_local  # noqa: E402
from research.mes_intraday.novel import gap_and_go  # noqa: E402

CHARTS_DIR = Path("research/charts")
SPLIT = date(2020, 1, 1)  # OOS (before) vs development (after)


def main() -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    df = load_spy_5min(Path(".data"))  # full cache, 2016 -> now
    bad = flag_corrupt_days_local(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()

    sig = gap_and_go(df)
    pol = ExitPolicy(label="x", stop_atr=1.0, time_exit=(13, 0))
    trades = simulate_with_exits(
        df,
        sig.entry_long,
        sig.entry_short,
        pol,
        contracts=1,
        commission_scenario="mid",
        slippage_scenario="one",
    )
    daily = pd.Series(0.0, index=pd.Index(sorted(set(df["date"]))))
    for t in trades:
        daily.loc[t.exit_ts.tz_convert(MARKET_TZ).date()] += t.pnl
    equity = INIT_CASH + daily.cumsum()
    x = pd.to_datetime(pd.Index(equity.index))

    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(x, equity.to_numpy(), lw=1.3, color="#2c3e50")
    ax.axhline(INIT_CASH, color="#7f8c8d", ls="--", lw=0.8, label=r"start \$2,000")

    split_ts = pd.Timestamp(SPLIT)
    ax.axvspan(x.min(), split_ts, color="#e74c3c", alpha=0.08)
    ax.axvspan(split_ts, x.max(), color="#27ae60", alpha=0.08)
    ax.axvline(split_ts, color="#555", ls=":", lw=1.0)

    # Annotate the two regimes with their realized annualized returns.
    ax.text(
        pd.Timestamp("2017-06-01"),
        equity.max() * 0.9,
        "OUT-OF-SAMPLE\n2016-2019\n~flat / negative\n(low-vol 2017, whipsaw 2018)",
        fontsize=9,
        ha="center",
        color="#c0392b",
        weight="bold",
    )
    ax.text(
        pd.Timestamp("2023-01-01"),
        equity.max() * 0.45,
        "DEVELOPMENT\n2020-2026\n+47%/yr",
        fontsize=9,
        ha="center",
        color="#1e8449",
        weight="bold",
    )

    ax.set_title(
        "Keeper strategy across 2016→2026 — SAME params (gap-and-go + ATR stop + 13:00 exit)\n"
        "The edge only appears in the 2020-2026 regime; it is not all-weather",
        fontsize=11,
    )
    ax.set_ylabel(r"Account equity (\$, 1 MES on \$2,000)")
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(True, alpha=0.25)

    fig.tight_layout()
    out = CHARTS_DIR / "mes_oos_2016_equity.png"
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
