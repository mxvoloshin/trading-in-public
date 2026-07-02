"""VectorBT-based backtesting track for fast strategy prototyping."""

from trade_vectorbt.adapter import to_ohlcv_dataframe
from trade_vectorbt.runner import VectorbtResult, run_vectorbt_backtest
from trade_vectorbt.signals import (
    Signals,
    atr_trail_signals,
    ma_cross_signals,
    orb_signals,
    rsi_revert_signals,
)
from trade_vectorbt.summary import VectorbtSummary, build_vectorbt_summary

PACKAGE_NAME = "trade_vectorbt"

__all__ = [
    "PACKAGE_NAME",
    "Signals",
    "VectorbtResult",
    "VectorbtSummary",
    "atr_trail_signals",
    "build_vectorbt_summary",
    "ma_cross_signals",
    "orb_signals",
    "rsi_revert_signals",
    "run_vectorbt_backtest",
    "to_ohlcv_dataframe",
]
