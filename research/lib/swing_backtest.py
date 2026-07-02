"""Swing / multi-day backtest harness on top of the existing vectorbt runner.

This is the overnight-friendly counterpart to ``research/lib/backtest.py``. The
intraday harness forces flat by EOD and hard-codes 78 five-minute bars per day;
this one lets positions be **held overnight and for multiple days**, works on any
timeframe (daily, 1h, 4h, 15m), and derives all calendar-based metrics
(annualization, drawdown duration, holding time) from the actual timestamp index
rather than an assumed bar-per-day count.

Cost model matches the research goal exactly::

    commission = entry_shares * rate + exit_shares * rate

VectorBT applies ``fees`` as a fraction of trade value on each side, so the
equivalent per-side fraction is ``rate / reference_price`` (reference = the
window's mean close, a documented approximation). Slippage in cents/share maps
the same way.

Account constraints (IBKR Reg T, $2,000):

- Headline runs are **1x, fully invested** so results are directly comparable to
  the intraday study and are not flattered by leverage.
- Reg T allows up to **2x** overnight (50% initial margin). Crucially, swing
  trades are *not* day trades, so the Pattern-Day-Trader rule that blocked the
  intraday study on a sub-$25k account does **not** apply here. The 2x levered
  projection is reported analytically (return and drawdown scale ~linearly for a
  fixed-fraction long book), not silently re-simulated -- vectorbt's percent
  sizing caps at available cash and would quietly stay at 1x.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from trade_vectorbt import Signals, run_vectorbt_backtest

# --- Cost scenarios (per the goal) ---------------------------------------
COMMISSION_RATES: dict[str, float] = {
    "none": 0.0,
    "tiered_low": 0.0005,
    "tiered_mid": 0.0020,
    "tiered_high": 0.0035,
    "fixed": 0.0050,
}

# Slippage in cents/share (one way). SPY's quoted spread is ~1 cent, so 0.5c is
# roughly half-spread, 1c crosses the spread, 2c is a stress assumption.
SLIPPAGE_CENTS: dict[str, float] = {
    "none": 0.0,
    "half_spread": 0.5,
    "full_spread": 1.0,
    "stress": 2.0,
}

# Small-account constraints.
INIT_CASH = 2_000.0
INITIAL_MARGIN = 0.50  # Reg T initial margin -> 2x buying power
MAINTENANCE_MARGIN = 0.25

# Trading days per year, used for annualizing the self-computed daily Sharpe.
TRADING_DAYS = 252


@dataclass(frozen=True, slots=True)
class SwingMetrics:
    """Full metric set for one swing/multi-day backtest run."""

    label: str
    timeframe: str
    commission_scenario: str
    slippage_scenario: str
    n_bars: int
    n_days: int
    span_days: int

    # Sizing / account
    init_cash: float
    leverage: float
    reference_price: float
    max_shares_1x: int
    max_shares_2x: int

    # Returns
    net_profit: float
    total_return_pct: float
    annualized_return_pct: float | None
    final_value: float
    gross_return_pct: float | None

    # Risk-adjusted (daily-return based, computed here for cross-timeframe parity)
    sharpe: float | None
    sortino: float | None
    calmar: float | None
    max_drawdown_pct: float | None
    max_dd_duration_days: int

    # Trade stats
    total_trades: int
    trades_per_month: float
    win_rate_pct: float | None
    profit_factor: float | None
    avg_win: float | None
    avg_loss: float | None
    expectancy: float | None
    largest_win: float | None
    largest_loss: float | None
    avg_hold_days: float | None
    exposure_pct: float | None

    # Daily
    best_day_pct: float | None
    worst_day_pct: float | None

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def _annualized(total_return: float, span_days: int) -> float | None:
    """CAGR from total return over a calendar span (365.25 days/yr)."""
    if span_days <= 0:
        return None
    base = 1.0 + total_return
    if base <= 0:
        return None
    years = span_days / 365.25
    return (base ** (1.0 / years) - 1.0) * 100.0


def _sf(x: object) -> float | None:
    """Coerce to a finite float or None (NaN/inf -> None) for clean JSON."""
    try:
        f = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if (np.isnan(f) or np.isinf(f)) else f


def underwater_duration_days(equity: pd.Series) -> int:
    """Longest time the equity curve spent below a prior peak, in calendar days.

    Standard "time under water": at each bar below the running peak we measure
    the wall-clock gap back to the peak that started the drawdown and keep the
    largest. Timeframe-agnostic (works for daily and intraday bars alike, unlike
    a fixed bars-per-day conversion) and needs no completed recovery -- an
    open drawdown at the end still counts its time-since-peak.
    """
    values = equity.to_numpy(dtype=float)
    idx = equity.index
    longest = pd.Timedelta(0)
    peak_val = values[0]
    peak_i = 0
    for i in range(1, len(values)):
        if values[i] >= peak_val:
            peak_val = values[i]
            peak_i = i
        else:
            longest = max(longest, idx[i] - idx[peak_i])
    return int(longest.days)


def _daily_risk_ratios(equity: pd.Series) -> tuple[float | None, float | None]:
    """Annualized Sharpe & Sortino from *daily* equity returns.

    Computed here (rather than via vectorbt's freq-based ratios) so the numbers
    are comparable across timeframes: an intraday frame with overnight gaps
    breaks vectorbt's frequency inference, but resampling equity to one point per
    trade date and annualizing by sqrt(252) is well-defined for every timeframe.
    """
    daily_eq = equity.groupby(equity.index.tz_convert("America/New_York").date).last()
    r = daily_eq.pct_change().dropna()
    if len(r) < 2 or r.std() == 0:
        return None, None
    sharpe = r.mean() / r.std() * np.sqrt(TRADING_DAYS)
    downside = r[r < 0].std()
    sortino = r.mean() / downside * np.sqrt(TRADING_DAYS) if downside and downside > 0 else None
    return _sf(sharpe), _sf(sortino)


def run_swing_backtest(
    df: pd.DataFrame,
    signals: Signals,
    *,
    label: str,
    timeframe: str,
    commission_scenario: str = "tiered_mid",
    slippage_scenario: str = "full_spread",
    init_cash: float = INIT_CASH,
    freq: str = "D",
) -> SwingMetrics:
    """Run one swing backtest with a cost scenario and return the full metric set.

    Positions may be held overnight / for multiple days (no EOD flatten). Runs
    1x fully invested; the 2x Reg T projection is reported analytically.
    """
    close = df["close"]
    ref_price = float(close.mean())

    # Cost mapping: $/share and cents/share -> fraction of trade value.
    rate = COMMISSION_RATES[commission_scenario]
    slip_cents = SLIPPAGE_CENTS[slippage_scenario]
    fees_frac = rate / ref_price
    slippage_frac = (slip_cents / 100.0) / ref_price

    # Reg T sizing sanity: how many whole shares $2,000 buys at 1x and 2x.
    max_shares_1x = int(init_cash // ref_price)
    max_shares_2x = int((init_cash / INITIAL_MARGIN) // ref_price)
    if max_shares_1x < 1:
        msg = f"impossible size: ref price {ref_price:.2f} exceeds 1x cash {init_cash:.2f}"
        raise ValueError(msg)

    result = run_vectorbt_backtest(
        close,
        signals.entries,
        signals.exits,
        init_cash=init_cash,
        fees=fees_frac,
        slippage=slippage_frac,
        direction="longonly",
        freq=freq,
    )
    pf: Any = result.portfolio

    gross = run_vectorbt_backtest(
        close,
        signals.entries,
        signals.exits,
        init_cash=init_cash,
        fees=0.0,
        slippage=0.0,
        direction="longonly",
        freq=freq,
    )

    total_return = float(pf.total_return())
    final_value = float(pf.final_value())
    net_profit = final_value - init_cash
    span_days = int((close.index.max() - close.index.min()).days)
    n_days = int(pd.Series(df.index.tz_convert("America/New_York").date).nunique())

    trades: Any = pf.trades
    total_trades = int(trades.count())
    rec: pd.DataFrame = trades.records_readable

    win_rate = _sf(trades.win_rate() * 100) if total_trades else None
    profit_factor = _sf(trades.profit_factor()) if total_trades else None
    expectancy = _sf(trades.expectancy()) if total_trades else None

    avg_win = avg_loss = largest_win = largest_loss = avg_hold_days = None
    if total_trades and "PnL" in rec.columns:
        pnl = rec["PnL"].astype(float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        avg_win = _sf(wins.mean()) if len(wins) else None
        avg_loss = _sf(losses.mean()) if len(losses) else None
        largest_win = _sf(pnl.max())
        largest_loss = _sf(pnl.min())
        if {"Entry Timestamp", "Exit Timestamp"}.issubset(rec.columns):
            hold = pd.to_datetime(rec["Exit Timestamp"]) - pd.to_datetime(rec["Entry Timestamp"])
            avg_hold_days = _sf(hold.dt.total_seconds().mean() / 86_400.0)

    try:
        exposure = _sf(float(pf.position_mask().mean()) * 100)
    except Exception:
        exposure = None

    equity = pf.value()
    max_dd_days = underwater_duration_days(equity)
    sharpe, sortino = _daily_risk_ratios(equity)

    daily_eq = equity.groupby(equity.index.tz_convert("America/New_York").date).last()
    daily_ret = daily_eq.pct_change().dropna()
    best_day = _sf(daily_ret.max() * 100) if len(daily_ret) else None
    worst_day = _sf(daily_ret.min() * 100) if len(daily_ret) else None
    max_dd = _sf(pf.max_drawdown() * 100)
    calmar = None
    ann = _annualized(total_return, span_days)
    if ann is not None and max_dd not in (None, 0):
        calmar = _sf(ann / abs(max_dd))  # type: ignore[arg-type]

    gross_ret = _sf(float(gross.portfolio.total_return()) * 100)
    trades_per_month = total_trades / (span_days / 30.44) if span_days else 0.0

    return SwingMetrics(
        label=label,
        timeframe=timeframe,
        commission_scenario=commission_scenario,
        slippage_scenario=slippage_scenario,
        n_bars=int(len(df)),
        n_days=n_days,
        span_days=span_days,
        init_cash=init_cash,
        leverage=1.0,
        reference_price=round(ref_price, 2),
        max_shares_1x=max_shares_1x,
        max_shares_2x=max_shares_2x,
        net_profit=round(net_profit, 2),
        total_return_pct=round(total_return * 100, 3),
        annualized_return_pct=ann,
        final_value=round(final_value, 2),
        gross_return_pct=gross_ret,
        sharpe=sharpe,
        sortino=sortino,
        calmar=calmar,
        max_drawdown_pct=max_dd,
        max_dd_duration_days=max_dd_days,
        total_trades=total_trades,
        trades_per_month=round(trades_per_month, 1),
        win_rate_pct=win_rate,
        profit_factor=profit_factor,
        avg_win=avg_win,
        avg_loss=avg_loss,
        expectancy=expectancy,
        largest_win=largest_win,
        largest_loss=largest_loss,
        avg_hold_days=avg_hold_days,
        exposure_pct=exposure,
        best_day_pct=best_day,
        worst_day_pct=worst_day,
    )


__all__ = [
    "COMMISSION_RATES",
    "INIT_CASH",
    "MAINTENANCE_MARGIN",
    "SLIPPAGE_CENTS",
    "SwingMetrics",
    "run_swing_backtest",
]
