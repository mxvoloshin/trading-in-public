"""Render the MES intraday study's headline chart: the account-ruin equity curve.

Recomputes the best strategy (ORB long+short) at 1 MES contract on $2,000 — both
the naive and the risk-managed variant — and plots the account equity path. The
point of the picture is that both curves cross **zero** (a wiped-out account) well
before any annual return is realized, plus a per-year P&L bar panel showing the
edge is regime-driven. Written to research/charts/mes_*.png (gitignored data stays
out; the chart is a sanitized aggregate).

Run: uv run python research/mes_intraday/make_chart.py
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
from research.mes_intraday.lib import (  # noqa: E402
    INIT_CASH,
    MARKET_TZ,
    flag_corrupt_days_local,
    orb_ls,
    simulate_mes,
)

CHARTS_DIR = Path("research/charts")


def _equity(df: pd.DataFrame, trades: list, init_cash: float = INIT_CASH) -> pd.Series:
    """Daily account equity path = init_cash + cumulative per-trade P&L (by exit date)."""
    all_dates = sorted(set(df["date"]))
    daily = pd.Series(0.0, index=pd.Index(all_dates))
    for t in trades:
        d = t.exit_ts.tz_convert(MARKET_TZ).date()
        daily.loc[d] += t.pnl
    return init_cash + daily.cumsum()


def main() -> None:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    df = load_spy_5min(Path(".data"))
    bad = flag_corrupt_days_local(df)
    if bad:
        df = df[~df["date"].isin(set(bad))].copy()

    sig = orb_ls(df)
    naive = simulate_mes(df, sig, contracts=1, commission_scenario="mid", slippage_scenario="one")
    managed = simulate_mes(
        df,
        sig,
        contracts=1,
        commission_scenario="mid",
        slippage_scenario="one",
        stop_frac=0.003,
        target_frac=0.006,
    )
    eq_naive = _equity(df, naive)
    eq_managed = _equity(df, managed)
    x = pd.to_datetime(pd.Index(eq_naive.index))

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 8), gridspec_kw={"height_ratios": [2.2, 1]})

    # --- Panel 1: account equity, 1 MES contract on $2,000 --------------------
    ax1.plot(x, eq_naive.to_numpy(), lw=1.3, color="#c0392b", label="ORB naive (signal exit)")
    ax1.plot(
        x,
        eq_managed.to_numpy(),
        lw=1.3,
        color="#2980b9",
        label="ORB risk-managed (0.3% stop / 0.6% tgt)",
    )
    ax1.axhline(INIT_CASH, color="#7f8c8d", ls="--", lw=0.9, label="starting equity $2,000")
    ax1.axhline(0, color="black", lw=1.1)
    ax1.fill_between(
        x, 0, eq_naive.to_numpy(), where=(eq_naive.to_numpy() < 0), color="#c0392b", alpha=0.15
    )
    ax1.set_title(
        "MES intraday ORB (long+short), 1 contract on a $2,000 account, 2020→2026\n"
        "Both variants drive the account below $0 (liquidated) before any annual return accrues",
        fontsize=11,
    )
    ax1.set_ylabel("Account equity ($)")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, alpha=0.25)

    # --- Panel 2: per-calendar-year P&L (regime dependence) -------------------
    per_year: dict[int, float] = {}
    for t in naive:
        y = t.exit_ts.tz_convert(MARKET_TZ).year
        per_year[y] = per_year.get(y, 0.0) + t.pnl
    years = sorted(per_year)
    vals = [per_year[y] for y in years]
    colors = ["#27ae60" if v >= 0 else "#c0392b" for v in vals]
    ax2.bar([str(y) for y in years], vals, color=colors)
    ax2.axhline(0, color="black", lw=0.9)
    ax2.set_title(
        "Naive ORB per-year P&L ($, 1 contract) — profits live in 2022+; 2020–21 losses come first",
        fontsize=9,
    )
    ax2.set_ylabel("P&L ($)")
    ax2.grid(True, axis="y", alpha=0.25)

    fig.tight_layout()
    out = CHARTS_DIR / "mes_orb_account_ruin.png"
    fig.savefig(out, dpi=120)
    print(f"wrote {out}")
    print(
        "naive final equity:",
        round(float(eq_naive.iloc[-1]), 2),
        "min:",
        round(float(eq_naive.min()), 2),
    )
    print(
        "managed final equity:",
        round(float(eq_managed.iloc[-1]), 2),
        "min:",
        round(float(eq_managed.min()), 2),
    )


if __name__ == "__main__":
    main()
