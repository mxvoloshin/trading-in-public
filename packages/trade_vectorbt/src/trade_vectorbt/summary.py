"""Extract portfolio metrics from a VectorBT run into a serializable summary.

This mirrors the existing ``BacktestSummary`` pattern in
``apps/research/src/trade_research_app/backtest/records.py``: a frozen dataclass
with JSON-safe ``to_json_dict()`` and an optional artifact write to disk under
``.data/backtests/vbt/``.

The existing engine's summary is far richer (traceability chain, MFE/MAE/R
diagnostics, 25+ breakdowns) - by design this summary captures only what
vectorbt provides: portfolio-level returns/ratios, drawdown, and basic trade
stats. Strategies that prove out here get promoted to the rigorous engine for
the full diagnostics (Phase 5 of the integration plan).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from trade_vectorbt.runner import VectorbtResult


def _safe_float(value: float) -> float | None:
    """Convert NaN/Inf floats to None so they serialize as JSON null.

    VectorBT returns NaN for metrics like ``win_rate`` when there are no
    trades, and Inf for ``sharpe_ratio`` when returns are constant (e.g. a
    flat no-trade portfolio). Neither is valid JSON, so we null them.
    """
    f = float(value)
    if math.isnan(f) or math.isinf(f):
        return None
    return f


def _max_drawdown_duration_bars(drawdown: pd.Series) -> int:
    """Count bars in the longest consecutive drawdown run.

    A drawdown bar is one where ``drawdown < 0`` (equity below a prior
    high-water mark). The duration is the longest unbroken run of such bars,
    in bar units (not calendar time).
    """
    in_dd = drawdown < 0
    max_duration = 0
    current = 0
    for val in in_dd:
        if val:
            current += 1
            if current > max_duration:
                max_duration = current
        else:
            current = 0
    return max_duration


def _cagr(total_return: float, start: pd.Timestamp, end: pd.Timestamp) -> float | None:
    """Compound annual growth rate from total return and calendar span.

    Uses actual calendar days (not bar count) for the time denominator, so it
    works correctly regardless of ``freq``. Returns None if the span is zero
    or total_return would produce a non-real root (e.g. total return < -100%).
    """
    days = (end - start).days
    if days <= 0:
        return None
    years = days / 365.25
    base = 1.0 + total_return
    if base <= 0:
        # Total loss exceeds 100% - CAGR is undefined.
        return None
    return base ** (1.0 / years) - 1.0


@dataclass(frozen=True, slots=True)
class VectorbtSummary:
    """Portable metrics snapshot from a vectorbt portfolio simulation.

    Fields are plain ``float | None``, ``int``, and ``str`` so ``to_json_dict``
    can serialize them without Decimal conversion (unlike the existing engine
    which uses ``Decimal`` throughout). ``None`` replaces NaN/Inf values that
    vectorbt produces when there are no trades or returns are constant.

    The ``output_path`` field tracks where the artifact was written but is
    excluded from the JSON payload, mirroring ``BacktestSummary``.
    """

    # Identity
    strategy_name: str
    start: str
    end: str
    n_bars: int

    # Config (mirrors VectorbtResult inputs so the artifact is self-describing)
    init_cash: float
    fees: float
    slippage: float
    direction: str
    freq: str | None
    sl_stop: float | str | None
    tp_stop: float | None
    sl_trail: bool

    # Portfolio metrics
    total_return: float | None
    cagr: float | None
    final_value: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    calmar_ratio: float | None
    omega_ratio: float | None
    max_drawdown: float | None
    max_drawdown_duration_bars: int

    # Trade stats
    total_trades: int
    long_trades: int
    short_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float | None
    profit_factor: float | None
    expectancy: float | None
    best_trade_return: float | None
    worst_trade_return: float | None

    output_path: Path | None

    def to_json_dict(self) -> dict[str, str | int | float | None]:
        """Serialize using JSON-safe primitives.

        Float values that are ``None`` (NaN/Inf) become JSON ``null``; non-None
        floats are stringified with ``str()`` for human-readable precision,
        mirroring the existing ``BacktestSummary`` pattern of ``str(Decimal)``.
        """
        _s = str  # local alias for brevity in the dict below
        return {
            "strategy_name": self.strategy_name,
            "start": self.start,
            "end": self.end,
            "n_bars": self.n_bars,
            "init_cash": _s(self.init_cash),
            "fees": _s(self.fees),
            "slippage": _s(self.slippage),
            "direction": self.direction,
            "freq": self.freq if self.freq is not None else "",
            "sl_stop": _s(self.sl_stop) if self.sl_stop is not None else "",
            "tp_stop": _s(self.tp_stop) if self.tp_stop is not None else "",
            "sl_trail": self.sl_trail,
            "total_return": _s(self.total_return) if self.total_return is not None else None,
            "cagr": _s(self.cagr) if self.cagr is not None else None,
            "final_value": _s(self.final_value),
            "sharpe_ratio": _s(self.sharpe_ratio) if self.sharpe_ratio is not None else None,
            "sortino_ratio": _s(self.sortino_ratio) if self.sortino_ratio is not None else None,
            "calmar_ratio": _s(self.calmar_ratio) if self.calmar_ratio is not None else None,
            "omega_ratio": _s(self.omega_ratio) if self.omega_ratio is not None else None,
            "max_drawdown": _s(self.max_drawdown) if self.max_drawdown is not None else None,
            "max_drawdown_duration_bars": self.max_drawdown_duration_bars,
            "total_trades": self.total_trades,
            "long_trades": self.long_trades,
            "short_trades": self.short_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": _s(self.win_rate) if self.win_rate is not None else None,
            "profit_factor": _s(self.profit_factor) if self.profit_factor is not None else None,
            "expectancy": _s(self.expectancy) if self.expectancy is not None else None,
            "best_trade_return": _s(self.best_trade_return)
            if self.best_trade_return is not None
            else None,
            "worst_trade_return": _s(self.worst_trade_return)
            if self.worst_trade_return is not None
            else None,
        }


def build_vectorbt_summary(
    result: VectorbtResult,
    *,
    strategy_name: str,
    output_path: Path | None = None,
) -> VectorbtSummary:
    """Extract portfolio metrics from a ``VectorbtResult`` and optionally write the JSON artifact.

    This is the Phase 3 analog of the existing engine's ``build_summary``: it
    reads metrics from the portfolio object, packs them into a frozen
    dataclass, and writes the JSON artifact to ``output_path`` (creating
    parent directories as needed). The ``output_path`` is stored on the
    returned summary but excluded from the JSON payload.

    Parameters:
        result: A ``VectorbtResult`` from :func:`run_vectorbt_backtest`.
        strategy_name: Label for the signal generator or strategy (e.g.
            ``"ma_cross"``). Stored in the artifact for identification.
        output_path: Where to write the JSON summary. ``None`` skips writing.
    """
    pf: Any = result.portfolio
    price = result.price

    # Identity from the price index. Cast to Timestamp via min/max to avoid
    # pandas-stub's broad Index element type (pyright with untyped pandas).
    start_ts = pd.Timestamp(price.index.min())
    end_ts = pd.Timestamp(price.index.max())
    start_str = start_ts.isoformat()
    end_str = end_ts.isoformat()
    n_bars = len(price)

    # Portfolio metrics -- vectorbt returns numpy float64; _safe_float
    # converts NaN/Inf to None for JSON safety.
    total_return = _safe_float(float(pf.total_return()))
    final_value = float(pf.final_value())
    sharpe = _safe_float(float(pf.sharpe_ratio()))
    sortino = _safe_float(float(pf.sortino_ratio()))
    calmar = _safe_float(float(pf.calmar_ratio()))
    omega = _safe_float(float(pf.omega_ratio()))
    max_dd = _safe_float(float(pf.max_drawdown()))

    # Max drawdown duration in bars (computed from the drawdown series).
    dd_series: pd.Series = pf.drawdown()
    max_dd_duration = _max_drawdown_duration_bars(dd_series)

    # CAGR from calendar span.
    cagr = _cagr(float(pf.total_return()), start_ts, end_ts) if total_return is not None else None

    # Trade stats from the trades object. vectorbt returns NaN for win_rate,
    # profit_factor, and expectancy when there are no trades.
    trades: Any = pf.trades
    total_trades = int(trades.count())
    win_rate = _safe_float(float(trades.win_rate()))
    profit_factor = _safe_float(float(trades.profit_factor()))
    expectancy = _safe_float(float(trades.expectancy()))

    # Long/short/winning/losing counts from the readable records table.
    records: pd.DataFrame = trades.records_readable
    if total_trades > 0 and "Direction" in records.columns and "PnL" in records.columns:
        long_trades = int((records["Direction"] == "Long").sum())
        short_trades = int((records["Direction"] == "Short").sum())
        winning_trades = int((records["PnL"] > 0).sum())
        losing_trades = int((records["PnL"] < 0).sum())

        # Best/worst trade return from the "Return" column (fraction of
        # position value, not dollar PnL).
        if "Return" in records.columns:
            trade_returns = records["Return"].astype(float)
            best_trade_return = _safe_float(float(trade_returns.max()))
            worst_trade_return = _safe_float(float(trade_returns.min()))
        else:
            best_trade_return = None
            worst_trade_return = None
    else:
        long_trades = 0
        short_trades = 0
        winning_trades = 0
        losing_trades = 0
        best_trade_return = None
        worst_trade_return = None

    summary = VectorbtSummary(
        strategy_name=strategy_name,
        start=start_str,
        end=end_str,
        n_bars=n_bars,
        init_cash=result.init_cash,
        fees=result.fees,
        slippage=result.slippage,
        direction=result.direction,
        freq=result.freq,
        # sl_stop can be a scalar float or a per-bar pd.Series (ATR trail).
        # Store scalars as-is; summarize a Series as "per_bar" since the actual
        # array isn't useful in a JSON metrics snapshot.
        sl_stop=("per_bar" if isinstance(result.sl_stop, pd.Series) else result.sl_stop),
        tp_stop=result.tp_stop,
        sl_trail=result.sl_trail,
        total_return=total_return,
        cagr=cagr,
        final_value=final_value,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        calmar_ratio=calmar,
        omega_ratio=omega,
        max_drawdown=max_dd,
        max_drawdown_duration_bars=max_dd_duration,
        total_trades=total_trades,
        long_trades=long_trades,
        short_trades=short_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        profit_factor=profit_factor,
        expectancy=expectancy,
        best_trade_return=best_trade_return,
        worst_trade_return=worst_trade_return,
        output_path=output_path,
    )

    # Write the artifact, mirroring the existing engine's idiom: create parent
    # directories, write JSON with indent=2 and sort_keys=True. The output_path
    # is stored on the summary but excluded from the JSON payload.
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary.to_json_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return summary


__all__ = ["VectorbtSummary", "build_vectorbt_summary"]
