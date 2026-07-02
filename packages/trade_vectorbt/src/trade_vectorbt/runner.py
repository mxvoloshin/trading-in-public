"""VectorBT portfolio runner: signal arrays in, simulation result out.

This is the fast-prototyping counterpart to the existing bar-by-bar engine in
``apps/research/src/trade_research_app/backtest/``. It wraps vectorbt's
``Portfolio.from_signals`` - which fills at the signal bar by default - so
results are quick but NOT directly comparable to the custom engine's
next-bar-open fills. See ``docs/architecture/vectorbt-integration-plan.md``
for the fill-timing divergence and cost-model mapping notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import vectorbt as vbt

_VALID_DIRECTIONS = frozenset({"longonly", "shortonly", "both"})


@dataclass(frozen=True, slots=True)
class VectorbtResult:
    """Outcome of a single vectorbt portfolio simulation.

    Wraps the vectorbt ``Portfolio`` object (accessed via ``.portfolio``) along
    with the inputs that produced it, so callers can inspect metrics, trades,
    and equity curves without re-deriving the simulation. Call portfolio
    methods directly for analysis::

        result.portfolio.total_return()
        result.portfolio.sharpe_ratio()
        result.portfolio.trades.records_readable

    Phase 3 will add a ``VectorbtSummary`` dataclass that extracts a portable
    metrics snapshot (Sharpe, Sortino, Calmar, drawdown, trade stats) from
    this result for artifact serialization.
    """

    # vbt.Portfolio - vectorbt ships without type stubs, so Any is the honest
    # annotation. The relaxed pyright execution environment for this package
    # suppresses the unknown-type diagnostics that would otherwise fire.
    portfolio: Any
    price: pd.Series
    entries: pd.Series
    exits: pd.Series
    init_cash: float
    # Fraction of trade value (0.001 = 0.1%), NOT per-share commission.
    fees: float
    slippage: float
    # Bar frequency for annualized metrics (e.g. "D", "5min"). None lets
    # vectorbt infer from the index, which breaks for intraday session gaps.
    freq: str | None
    sl_stop: float | pd.Series | None
    tp_stop: float | None
    sl_trail: bool
    direction: str


def run_vectorbt_backtest(
    price: pd.Series,
    entries: pd.Series,
    exits: pd.Series,
    *,
    init_cash: float = 10_000.0,
    fees: float = 0.0,
    slippage: float = 0.0,
    sl_stop: float | pd.Series | None = None,
    tp_stop: float | None = None,
    sl_trail: bool = False,
    direction: str = "both",
    freq: str | None = None,
) -> VectorbtResult:
    """Run a vectorbt portfolio simulation from signal arrays.

    Parameters:
        price: Close-price series with a tz-aware DatetimeIndex (the ``close``
            column from :func:`to_ohlcv_dataframe`).
        entries: Boolean series - True on bars where a new position should open.
        exits: Boolean series - True on bars where an open position should close.
        init_cash: Starting cash for the simulated account.
        fees: Transaction cost as a **fraction of trade value** (0.001 = 0.1%).
            This differs from the custom engine's ``BacktestCostModel`` which
            uses per-share commission + minimum; the mapping is approximate and
            documented in the integration plan.
        slippage: One-way slippage as a fraction of price (0.001 = 0.1%).
        sl_stop: Stop-loss as a fraction of price (0.03 = 3%). Can be a scalar
            or a per-bar series (for ATR-scaled stops). Requires ``sl_trail``
            or a matching exit signal to take effect.
        tp_stop: Take-profit as a fraction of price (0.05 = 5%).
        sl_trail: If True, the stop ratchets with the high-water mark (trailing
            stop). If False, ``sl_stop`` is a fixed level from entry.
        direction: "longonly", "shortonly", or "both" (long/short flip on exit
            signals).
        freq: Bar frequency for annualized metrics (e.g. "D", "5min"). VectorBT
            infers from the index, but intraday data with session gaps breaks
            inference - pass an explicit value for correct Sharpe/Sortino/Calmar.

    Returns:
        A :class:`VectorbtResult` wrapping the simulated portfolio.

    Raises:
        ValueError: If ``direction`` is invalid or ``fees``/``slippage`` are
            negative.
    """
    if direction not in _VALID_DIRECTIONS:
        msg = f"direction must be one of {sorted(_VALID_DIRECTIONS)}, got {direction!r}"
        raise ValueError(msg)
    if fees < 0:
        msg = f"fees must be non-negative, got {fees}"
        raise ValueError(msg)
    if slippage < 0:
        msg = f"slippage must be non-negative, got {slippage}"
        raise ValueError(msg)

    portfolio = vbt.Portfolio.from_signals(
        price,
        entries,
        exits,
        init_cash=init_cash,
        fees=fees,
        slippage=slippage,
        sl_stop=sl_stop,
        tp_stop=tp_stop,
        sl_trail=sl_trail,
        direction=direction,
        freq=freq,
    )
    return VectorbtResult(
        portfolio=portfolio,
        price=price,
        entries=entries,
        exits=exits,
        init_cash=init_cash,
        fees=fees,
        slippage=slippage,
        freq=freq,
        sl_stop=sl_stop,
        tp_stop=tp_stop,
        sl_trail=sl_trail,
        direction=direction,
    )


__all__ = ["VectorbtResult", "run_vectorbt_backtest"]
