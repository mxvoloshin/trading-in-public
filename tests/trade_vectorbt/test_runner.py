from __future__ import annotations

import pandas as pd
import pytest
from trade_vectorbt import (
    VectorbtResult,
    atr_trail_signals,
    ma_cross_signals,
    run_vectorbt_backtest,
)


def test_run_vectorbt_backtest_with_ma_cross(synthetic_ohlcv: pd.DataFrame) -> None:
    close = synthetic_ohlcv["close"]
    sig = ma_cross_signals(close, fast=10, slow=30)
    result = run_vectorbt_backtest(
        close,
        sig.entries,
        sig.exits,
        init_cash=10_000,
        fees=0.001,
        slippage=0.001,
        freq="D",
    )
    assert isinstance(result, VectorbtResult)
    # total_return is a float (can be positive or negative).
    total_return = float(result.portfolio.total_return())
    assert isinstance(total_return, float)
    # The portfolio value series has the same length as the input price.
    assert len(result.portfolio.value()) == len(close)


def test_run_vectorbt_backtest_zero_costs(synthetic_ohlcv: pd.DataFrame) -> None:
    """With zero fees/slippage, the result should still produce valid metrics."""
    sig = ma_cross_signals(synthetic_ohlcv["close"], fast=10, slow=30)
    result = run_vectorbt_backtest(
        synthetic_ohlcv["close"],
        sig.entries,
        sig.exits,
        freq="D",
    )
    assert result.fees == 0.0
    assert result.slippage == 0.0
    # Sharpe is a float even with zero costs.
    assert isinstance(float(result.portfolio.sharpe_ratio()), float)


def test_run_vectorbt_backtest_with_atr_trail(synthetic_ohlcv: pd.DataFrame) -> None:
    df = synthetic_ohlcv
    sig = atr_trail_signals(df["high"], df["low"], df["close"], window=14, multiplier=1.0)
    result = run_vectorbt_backtest(
        df["close"],
        sig.entries,
        sig.exits,
        init_cash=10_000,
        fees=0.001,
        slippage=0.001,
        sl_stop=sig.sl_stop,
        sl_trail=True,
        direction="longonly",
        freq="D",
    )
    assert isinstance(result, VectorbtResult)
    assert result.sl_trail is True
    assert result.direction == "longonly"
    # The ATR trail should produce at least one trade on 200 bars.
    assert len(result.portfolio.trades.records_readable) >= 1


def test_run_vectorbt_backtest_tp_stop(synthetic_ohlcv: pd.DataFrame) -> None:
    sig = ma_cross_signals(synthetic_ohlcv["close"], fast=10, slow=30)
    result = run_vectorbt_backtest(
        synthetic_ohlcv["close"],
        sig.entries,
        sig.exits,
        init_cash=10_000,
        fees=0.001,
        tp_stop=0.05,
        freq="D",
    )
    assert result.tp_stop == 0.05
    assert isinstance(float(result.portfolio.total_return()), float)


def test_run_vectorbt_backtest_invalid_direction(synthetic_ohlcv: pd.DataFrame) -> None:
    sig = ma_cross_signals(synthetic_ohlcv["close"], fast=10, slow=30)
    with pytest.raises(ValueError, match="direction must be one of"):
        run_vectorbt_backtest(
            synthetic_ohlcv["close"],
            sig.entries,
            sig.exits,
            direction="invalid",
        )


def test_run_vectorbt_backtest_negative_fees(synthetic_ohlcv: pd.DataFrame) -> None:
    sig = ma_cross_signals(synthetic_ohlcv["close"], fast=10, slow=30)
    with pytest.raises(ValueError, match="fees must be non-negative"):
        run_vectorbt_backtest(
            synthetic_ohlcv["close"],
            sig.entries,
            sig.exits,
            fees=-0.001,
        )


def test_run_vectorbt_backtest_negative_slippage(synthetic_ohlcv: pd.DataFrame) -> None:
    sig = ma_cross_signals(synthetic_ohlcv["close"], fast=10, slow=30)
    with pytest.raises(ValueError, match="slippage must be non-negative"):
        run_vectorbt_backtest(
            synthetic_ohlcv["close"],
            sig.entries,
            sig.exits,
            slippage=-0.001,
        )
