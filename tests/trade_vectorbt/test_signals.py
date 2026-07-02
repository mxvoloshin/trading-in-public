from __future__ import annotations

import pandas as pd
import pytest
from trade_vectorbt import (
    Signals,
    atr_trail_signals,
    ma_cross_signals,
    rsi_revert_signals,
)

# ---------------------------------------------------------------------------
# ma_cross_signals
# ---------------------------------------------------------------------------


def test_ma_cross_signals_returns_boolean_series(synthetic_ohlcv: pd.DataFrame) -> None:
    close = synthetic_ohlcv["close"]
    sig = ma_cross_signals(close, fast=10, slow=30)
    assert isinstance(sig, Signals)
    assert isinstance(sig.entries, pd.Series)
    assert isinstance(sig.exits, pd.Series)
    assert len(sig.entries) == len(close)
    assert len(sig.exits) == len(close)
    # Boolean dtype from vectorbt crossover detection.
    assert sig.entries.dtype == bool
    assert sig.exits.dtype == bool
    assert sig.sl_stop is None


def test_ma_cross_signals_produces_events(synthetic_ohlcv: pd.DataFrame) -> None:
    """With 200 bars and an upward-drifting random walk, crossovers should fire."""
    sig = ma_cross_signals(synthetic_ohlcv["close"], fast=10, slow=30)
    assert int(sig.entries.sum()) >= 1
    assert int(sig.exits.sum()) >= 1


def test_ma_cross_signals_rejects_fast_ge_slow(synthetic_ohlcv: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="must be smaller"):
        ma_cross_signals(synthetic_ohlcv["close"], fast=30, slow=10)
    with pytest.raises(ValueError, match="must be smaller"):
        ma_cross_signals(synthetic_ohlcv["close"], fast=20, slow=20)


# ---------------------------------------------------------------------------
# rsi_revert_signals
# ---------------------------------------------------------------------------


def test_rsi_revert_signals_returns_boolean_series(synthetic_ohlcv: pd.DataFrame) -> None:
    close = synthetic_ohlcv["close"]
    sig = rsi_revert_signals(close, window=14, lower=30, upper=70)
    assert isinstance(sig, Signals)
    assert sig.entries.dtype == bool
    assert sig.exits.dtype == bool
    assert len(sig.entries) == len(close)
    assert sig.sl_stop is None


def test_rsi_revert_signals_rejects_invalid_thresholds(synthetic_ohlcv: pd.DataFrame) -> None:
    close = synthetic_ohlcv["close"]
    with pytest.raises(ValueError, match="lower.*must be in"):
        rsi_revert_signals(close, window=14, lower=-1, upper=70)
    with pytest.raises(ValueError, match="upper.*must be in"):
        rsi_revert_signals(close, window=14, lower=30, upper=101)
    with pytest.raises(ValueError, match="must be below upper"):
        rsi_revert_signals(close, window=14, lower=70, upper=30)


# ---------------------------------------------------------------------------
# atr_trail_signals
# ---------------------------------------------------------------------------


def test_atr_trail_signals_returns_stop_series(synthetic_ohlcv: pd.DataFrame) -> None:
    df = synthetic_ohlcv
    sig = atr_trail_signals(df["high"], df["low"], df["close"], window=14, multiplier=2.0)
    assert isinstance(sig, Signals)
    assert sig.sl_stop is not None
    # Stop values are fractions of price, so all positive and finite.
    assert (sig.sl_stop > 0).all()
    assert sig.sl_stop.isna().sum() == 0
    # Entries only after ATR warmup period.
    assert int(sig.entries.iloc[:14].sum()) == 0
    assert sig.entries.iloc[14:].any()
    # Exits are all False - exit only via the trailing stop.
    assert not sig.exits.any()


def test_atr_trail_signals_rejects_non_positive_multiplier(
    synthetic_ohlcv: pd.DataFrame,
) -> None:
    df = synthetic_ohlcv
    with pytest.raises(ValueError, match="multiplier.*must be positive"):
        atr_trail_signals(df["high"], df["low"], df["close"], window=14, multiplier=0)
    with pytest.raises(ValueError, match="multiplier.*must be positive"):
        atr_trail_signals(df["high"], df["low"], df["close"], window=14, multiplier=-1)
