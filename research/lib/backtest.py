"""Realistic intraday backtest harness on top of the existing vectorbt runner.

Wraps ``trade_vectorbt.run_vectorbt_backtest`` but adds the pieces the research
goal requires and that the thin vbt summary omits:

- **IBKR per-share commissions** mapped into vectorbt's fraction-of-value ``fees``
  model, using the window's mean price as the reference (documented approximation).
- **Configurable slippage** expressed in cents/share, converted the same way.
- **Reg T small-account sizing**: $2,000 start, 50% initial margin => 2x intraday
  buying power. Position value is capped and impossible sizes are rejected.
- **Full metric set**: trades/month, expectancy, avg hold, exposure, best/worst
  day, drawdown duration in days, gross-vs-net, plus everything the vbt summary
  already computes.

Commission model (per the goal):
    commission = entry_shares * rate + exit_shares * rate
Since vectorbt applies ``fees`` as a fraction of trade value on *each* side,
the equivalent per-side fraction is ``rate / reference_price``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd
from trade_vectorbt import Signals, run_vectorbt_backtest

# --- Cost scenarios (per the goal) ---------------------------------------
# IBKR per-share commission rates. "none" is reference-only.
COMMISSION_RATES: dict[str, float] = {
    "none": 0.0,
    "tiered_low": 0.0005,
    "tiered_mid": 0.0020,
    "tiered_high": 0.0035,
    "fixed": 0.0050,
}

# Slippage scenarios in cents/share (one way). SPY's quoted spread is ~1 cent,
# so 0.5c ~= half-spread (marketable-limit), 1c ~= cross-the-spread, 2c ~= stress.
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


SignalFn = Callable[..., Signals]


@dataclass(frozen=True, slots=True)
class BacktestMetrics:
    """Full metric set for one intraday backtest run."""

    label: str
    commission_scenario: str
    slippage_scenario: str
    n_bars: int
    n_days: int
    span_days: int

    # Sizing / account
    init_cash: float
    leverage: float
    reference_price: float
    max_shares: int

    # Returns
    net_profit: float
    total_return_pct: float
    annualized_return_pct: float | None
    final_value: float
    gross_return_pct: float | None

    # Risk-adjusted
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
    avg_hold_minutes: float | None
    exposure_pct: float | None

    # Daily
    best_day_pct: float | None
    worst_day_pct: float | None

    def to_row(self) -> dict[str, Any]:
        return asdict(self)


def _annualized(total_return: float, span_days: int) -> float | None:
    if span_days <= 0:
        return None
    base = 1.0 + total_return
    if base <= 0:
        return None
    years = span_days / 365.25
    return (base ** (1.0 / years) - 1.0) * 100.0


def run_intraday_backtest(
    df: pd.DataFrame,
    signals: Signals,
    *,
    label: str,
    commission_scenario: str = "tiered_mid",
    slippage_scenario: str = "full_spread",
    init_cash: float = INIT_CASH,
    freq: str = "5min",
) -> BacktestMetrics:
    """Run one intraday backtest with a given cost scenario and return full metrics.

    Runs fully invested (1x cash, no margin). Because the strategy is flat
    overnight and deploys a fixed fraction of equity, Reg T intraday leverage
    (up to 2x with 50% initial margin) scales both the return and the drawdown
    roughly linearly — so levered figures are projected analytically in the
    report rather than re-simulated here. (VectorBT's ``from_signals`` caps
    percent sizing at available cash and does not model borrowing, so a ``size``
    override would silently stay at 1x and mislead.)
    """
    close = df["close"]
    ref_price = float(close.mean())

    # --- Cost mapping: per-share cents -> fraction of trade value ---------
    rate = COMMISSION_RATES[commission_scenario]  # $/share
    slip_cents = SLIPPAGE_CENTS[slippage_scenario]  # cents/share one-way
    fees_frac = rate / ref_price
    slippage_frac = (slip_cents / 100.0) / ref_price

    # --- Reg T sizing sanity ---------------------------------------------
    # With 50% initial margin, $2,000 controls up to $4,000 notional intraday.
    buying_power = init_cash / INITIAL_MARGIN
    max_shares = int(buying_power // ref_price)
    if max_shares < 1:
        msg = (
            f"impossible position size: reference price {ref_price:.2f} exceeds "
            f"buying power {buying_power:.2f} (need >= 1 share)"
        )
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

    # --- Gross (no-cost) run for cost attribution ------------------------
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

    # --- Core metrics -----------------------------------------------------
    total_return = float(pf.total_return())
    final_value = float(pf.final_value())
    net_profit = final_value - init_cash
    span_days = int((close.index.max() - close.index.min()).days)
    n_days = int(pd.Series(df.index.tz_convert("America/New_York").date).nunique())

    def _sf(x: float) -> float | None:
        f = float(x)
        return None if (np.isnan(f) or np.isinf(f)) else f

    trades: Any = pf.trades
    total_trades = int(trades.count())
    rec: pd.DataFrame = trades.records_readable

    win_rate = _sf(trades.win_rate() * 100) if total_trades else None
    profit_factor = _sf(trades.profit_factor()) if total_trades else None
    expectancy = _sf(trades.expectancy()) if total_trades else None

    avg_win = avg_loss = largest_win = largest_loss = avg_hold_min = None
    if total_trades and "PnL" in rec.columns:
        pnl = rec["PnL"].astype(float)
        wins = pnl[pnl > 0]
        losses = pnl[pnl < 0]
        avg_win = _sf(wins.mean()) if len(wins) else None
        avg_loss = _sf(losses.mean()) if len(losses) else None
        largest_win = _sf(pnl.max())
        largest_loss = _sf(pnl.min())
        # Hold time from entry/exit timestamps (vectorbt 1.0 readable columns).
        if {"Entry Timestamp", "Exit Timestamp"}.issubset(rec.columns):
            hold = pd.to_datetime(rec["Exit Timestamp"]) - pd.to_datetime(rec["Entry Timestamp"])
            avg_hold_min = _sf(hold.dt.total_seconds().mean() / 60.0)

    # Exposure: fraction of bars holding a position.
    try:
        exposure = _sf(float(pf.position_mask().mean()) * 100)
    except Exception:
        exposure = None

    # Drawdown duration in days (bars -> calendar days via 78 bars/day).
    dd = pf.drawdown()
    in_dd = (dd < 0).values
    max_run = cur = 0
    for v in in_dd:
        cur = cur + 1 if v else 0
        max_run = max(max_run, cur)
    max_dd_days = int(round(max_run / 78.0))

    # Daily returns (best/worst day) from equity curve.
    equity = pf.value()
    daily_eq = equity.groupby(equity.index.tz_convert("America/New_York").date).last()
    daily_ret = daily_eq.pct_change().dropna()
    best_day = _sf(daily_ret.max() * 100) if len(daily_ret) else None
    worst_day = _sf(daily_ret.min() * 100) if len(daily_ret) else None

    gross_ret = _sf(float(gross.portfolio.total_return()) * 100)
    trades_per_month = total_trades / (span_days / 30.44) if span_days else 0.0

    return BacktestMetrics(
        label=label,
        commission_scenario=commission_scenario,
        slippage_scenario=slippage_scenario,
        n_bars=int(len(df)),
        n_days=n_days,
        span_days=span_days,
        init_cash=init_cash,
        leverage=1.0,
        reference_price=round(ref_price, 2),
        max_shares=max_shares,
        net_profit=round(net_profit, 2),
        total_return_pct=round(total_return * 100, 3),
        annualized_return_pct=_annualized(total_return, span_days),
        final_value=round(final_value, 2),
        gross_return_pct=gross_ret,
        sharpe=_sf(pf.sharpe_ratio()),
        sortino=_sf(pf.sortino_ratio()),
        calmar=_sf(pf.calmar_ratio()),
        max_drawdown_pct=_sf(pf.max_drawdown() * 100),
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
        avg_hold_minutes=avg_hold_min,
        exposure_pct=exposure,
        best_day_pct=best_day,
        worst_day_pct=worst_day,
    )


__all__ = [
    "COMMISSION_RATES",
    "INIT_CASH",
    "SLIPPAGE_CENTS",
    "BacktestMetrics",
    "run_intraday_backtest",
]
