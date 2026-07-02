"""Shared fixtures for trade_vectorbt tests.

Generates a synthetic daily OHLCV DataFrame with enough bars for indicator
warmup and crossover/stop events. Uses a fixed seed so results are reproducible.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def synthetic_ohlcv() -> pd.DataFrame:
    """200 daily OHLCV bars (tz-aware UTC) with a mild uptrend and noise."""
    idx = pd.date_range("2025-01-01", periods=200, freq="D", tz="UTC")
    rng = np.random.default_rng(42)
    # Random walk with a slight upward drift so MA crossovers actually fire.
    close = pd.Series(100 + rng.standard_normal(200).cumsum() + np.arange(200) * 0.05, index=idx)
    spread = rng.uniform(0.1, 1.5, 200)
    high = close + spread
    low = close - spread
    volume = pd.Series(rng.integers(100, 10_000, 200), index=idx)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close, "volume": volume},
        index=idx,
    )
