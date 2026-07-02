# %% [markdown]
# # 2. RSI Mean-Reversion Walkthrough
#
# Fast-prototyping an RSI mean-reversion strategy with VectorBT.
#
# Buys when RSI dips below `lower` (oversold), exits when RSI rises above
# `upper` (momentum normalises). A classic mean-reversion reference that
# pairs best with `direction="longonly"`.
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
    rsi_revert_signals,
    run_vectorbt_backtest,
    to_ohlcv_dataframe,
)

# %% [markdown]
# ## Load bars from the local cache
#
# Fallback to synthetic data if no cached bars are available.

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
    import numpy as np

    rng = np.random.default_rng(42)
    idx = pd.date_range("2025-01-01", periods=200, freq="D", tz="UTC")
    # Higher-amplitude sine wave so RSI dips below 30 and above 70.
    close = pd.Series(100 + 5 * np.sin(np.arange(200) / 10) + rng.standard_normal(200) * 0.5, index=idx)
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
# ## Generate RSI mean-reversion signals
#
# RSI(14) below 30 = enter long (oversold); above 70 = exit (normalised).

# %%
close = df["close"]
signals = rsi_revert_signals(close, window=14, lower=30, upper=70)

n_entries = int(signals.entries.sum())
n_exits = int(signals.exits.sum())
print(f"Entries: {n_entries}, Exits: {n_exits}")

# %% [markdown]
# ## Run the portfolio simulation
#
# Mean-reversion works best with longonly direction (we're buying dips, not
# shorting strength). A small fee is applied to see the cost impact.

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

# %%
summary = build_vectorbt_summary(
    result,
    strategy_name="rsi-revert",
    output_path=Path(".data/backtests/vbt/rsi-revert/demo_summary.json"),
)

print(f"Strategy: {summary.strategy_name}")
print(f"Bars: {summary.n_bars}")
print(f"Total return: {summary.total_return}")
print(f"CAGR: {summary.cagr}")
print(f"Sharpe: {summary.sharpe_ratio}")
print(f"Sortino: {summary.sortino_ratio}")
print(f"Max drawdown: {summary.max_drawdown}")
print(f"Win rate: {summary.win_rate}")
print(f"Profit factor: {summary.profit_factor}")
print(f"Expectancy: {summary.expectancy}")
print(f"Total trades: {summary.total_trades}")
print(f"Output: {summary.output_path}")

# %% [markdown]
# ## Plot the equity curve and trades

# %%
fig = result.portfolio.plot()
fig.show()

# %% [markdown]
# ## Compare RSI against the price
#
# Overlay the RSI indicator on the price chart to see when entries/exits fire.

# %%
import vectorbt as vbt

rsi = vbt.RSI.run(close, window=14).rsi
rsi.vbt.plot().show()