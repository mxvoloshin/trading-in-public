# %% [markdown]
# # 1. MA Crossover Walkthrough
#
# Fast-prototyping an MA crossover strategy with VectorBT.
#
# This notebook demonstrates the full workflow:
# 1. Load bars from the local cache (or generate synthetic data).
# 2. Convert to the OHLCV DataFrame that vectorbt expects.
# 3. Generate MA crossover entry/exit signals.
# 4. Run the portfolio simulation.
# 5. Extract metrics into a summary artifact.
# 6. Plot the equity curve and trades.
#
# The existing bar-by-bar engine fills at next-bar-open with no lookahead;
# vectorbt fills at the signal bar by default. This divergence is documented
# in `docs/architecture/vectorbt-integration-plan.md` — results from the two
# tracks are NOT directly comparable without accounting for fill timing.
#
# **Prerequisites:** Run `uv sync` and optionally pre-fetch data with:
# ```
# uv run python -m trade_research_app market-data fetch --symbol SPY --start 2025-01-01 --end 2025-06-30
# ```

# %%
from pathlib import Path

import pandas as pd

from trade_data import HistoricalBarsRequest, Instrument, LocalMarketDataStore
from trade_data.sessions import get_market_session_config
from trade_vectorbt import (
    build_vectorbt_summary,
    ma_cross_signals,
    run_vectorbt_backtest,
    to_ohlcv_dataframe,
)

# %% [markdown]
# ## Load bars from the local cache
#
# We use the same `LocalMarketDataStore` API as the existing engine.
# If no cached data is available, synthetic bars are generated so the
# notebook is always runnable.

# %%
request = HistoricalBarsRequest(
    instrument=Instrument.us_equity("SPY"),
    timeframe="5Min",
    start_utc=pd.Timestamp("2025-01-01", tz="UTC"),
    end_utc=pd.Timestamp("2025-07-01", tz="UTC"),
)
session_config = get_market_session_config("XNYS")
store = LocalMarketDataStore(Path(".data"))
bars = store.load_bars(request, session_config)

if not bars:
    # No cached data — generate 200 synthetic daily bars so the notebook
    # is runnable without pre-fetching. Replace this by running
    # `market-data fetch` first for real results.
    import numpy as np

    rng = np.random.default_rng(42)
    idx = pd.date_range("2025-01-01", periods=200, freq="D", tz="UTC")
    close = pd.Series(100 + rng.standard_normal(200).cumsum() + np.arange(200) * 0.05, index=idx)
    spread = rng.uniform(0.1, 1.5, 200)
    df = pd.DataFrame(
        {
            "open": close,
            "high": close + spread,
            "low": close - spread,
            "close": close,
            "volume": rng.integers(100, 10_000, 200),
        },
        index=idx,
    )
    print("Using synthetic daily data (no cached bars found).")
else:
    df = to_ohlcv_dataframe(bars)
    print(f"Loaded {len(df)} bars from cache ({df.index[0]} to {df.index[-1]}).")

df.head()

# %% [markdown]
# ## Generate MA crossover signals
#
# MA(10) crossing above MA(30) = entry; crossing below = exit.
# VectorBT's `vbt.crossed_above` / `crossed_below` Series accessors detect
# the exact crossover bar.

# %%
close = df["close"]
signals = ma_cross_signals(close, fast=10, slow=30)

n_entries = int(signals.entries.sum())
n_exits = int(signals.exits.sum())
print(f"Entries: {n_entries}, Exits: {n_exits}")

# %% [markdown]
# ## Run the portfolio simulation
#
# `run_vectorbt_backtest` wraps `vbt.Portfolio.from_signals` with validation.
# Fees are a fraction of trade value (0.001 = 0.1%), not a per-share commission.
# The `freq` parameter is important for intraday data — session gaps break
# vectorbt's auto-inference of annualization periods.

# %%
result = run_vectorbt_backtest(
    close,
    signals.entries,
    signals.exits,
    init_cash=10_000.0,
    fees=0.001,
    slippage=0.0005,
    direction="longonly",
    freq="5min" if request.timeframe == "5Min" else "D",
)

print(f"Total return: {result.portfolio.total_return():.4f}")
print(f"Sharpe ratio: {result.portfolio.sharpe_ratio():.4f}")
print(f"Max drawdown: {result.portfolio.max_drawdown():.4f}")
print(f"Total trades: {result.portfolio.trades.count()}")

# %% [markdown]
# ## Build the summary artifact
#
# `build_vectorbt_summary` extracts 30+ metrics into a frozen dataclass
# and optionally writes a JSON artifact under `.data/backtests/vbt/`.

# %%
summary = build_vectorbt_summary(
    result,
    strategy_name="ma-cross",
    output_path=Path(".data/backtests/vbt/ma-cross/demo_summary.json"),
)

print(f"Strategy: {summary.strategy_name}")
print(f"Bars: {summary.n_bars}")
print(f"Total return: {summary.total_return}")
print(f"CAGR: {summary.cagr}")
print(f"Sharpe: {summary.sharpe_ratio}")
print(f"Sortino: {summary.sortino_ratio}")
print(f"Calmar: {summary.calmar_ratio}")
print(f"Max drawdown: {summary.max_drawdown}")
print(f"Max DD duration (bars): {summary.max_drawdown_duration_bars}")
print(f"Win rate: {summary.win_rate}")
print(f"Profit factor: {summary.profit_factor}")
print(f"Total trades: {summary.total_trades}")
print(f"Output: {summary.output_path}")

# %% [markdown]
# ## Plot the equity curve and trades
#
# VectorBT's `pf.plot()` produces an interactive plotly figure with the equity
# curve, drawdown, and trade markers. Requires `plotly` (installed with vectorbt).

# %%
fig = result.portfolio.plot()
fig.show()

# %% [markdown]
# ## Plot the trade records
#
# The trades plot shows entry/exit points on the price chart.

# %%
fig_trades = result.portfolio.trades.plot()
fig_trades.show()