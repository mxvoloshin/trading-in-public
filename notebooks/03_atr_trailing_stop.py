# %% [markdown]
# # 3. ATR Trailing-Stop Walkthrough
#
# Fast-prototyping an always-in long with a volatility-scaled trailing stop.
#
# VectorBT's ATR indicator calculates the Average True Range from high/low/close.
# The stop distance is `ATR * multiplier / close` (a fraction of price), passed
# as a per-bar `sl_stop` Series with `sl_trail=True`. The stop ratchets with
# the high-water mark — unlike the MA/RSI strategies which use discrete exit signals.
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
    atr_trail_signals,
    build_vectorbt_summary,
    run_vectorbt_backtest,
    to_ohlcv_dataframe,
)

# %% [markdown]
# ## Load bars from the local cache
#
# ATR needs high/low/close (true range uses the prior close), so we pass
# all three columns to the signal generator. Synthetic fallback uses a
# sine-wave with varying ranges so ATR is non-trivial.

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
    close = pd.Series(100 + rng.standard_normal(200).cumsum() + np.arange(200) * 0.05, index=idx)
    # Varying spread so ATR changes over time.
    spread = rng.uniform(0.5, 3.0, 200)
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
# ## Generate ATR trailing-stop signals
#
# `atr_trail_signals` returns always-in entries (after the warmup period),
# no discrete exits (the trailing stop handles exits), and a per-bar `sl_stop`
# Series to pass to the runner with `sl_trail=True`.

# %%
high = df["high"]
low = df["low"]
close = df["close"]

signals = atr_trail_signals(high, low, close, window=14, multiplier=2.0)

n_entries = int(signals.entries.sum())
print(f"Entry bars (after warmup): {n_entries}")
print(f"sl_stop type: {type(signals.sl_stop).__name__}")
print(f"sl_stop range: {signals.sl_stop.dropna().min():.4f} to {signals.sl_stop.dropna().max():.4f}")

# %% [markdown]
# ## Run the portfolio simulation
#
# The per-bar `sl_stop` Series is passed directly. `sl_trail=True` tells
# vectorbt to ratchet the stop with the high-water mark (trailing stop).

# %%
result = run_vectorbt_backtest(
    close,
    signals.entries,
    signals.exits,
    init_cash=10_000.0,
    fees=0.001,
    slippage=0.0005,
    sl_stop=signals.sl_stop,
    sl_trail=True,
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
# The summary records `sl_stop="per_bar"` (the Series is summarised as the
# label `"per_bar"` in JSON) and `sl_trail=True`.

# %%
summary = build_vectorbt_summary(
    result,
    strategy_name="atr-trail",
    output_path=Path(".data/backtests/vbt/atr-trail/demo_summary.json"),
)

print(f"Strategy: {summary.strategy_name}")
print(f"Bars: {summary.n_bars}")
print(f"Total return: {summary.total_return}")
print(f"CAGR: {summary.cagr}")
print(f"Sharpe: {summary.sharpe_ratio}")
print(f"Max drawdown: {summary.max_drawdown}")
print(f"Max DD duration (bars): {summary.max_drawdown_duration_bars}")
print(f"Win rate: {summary.win_rate}")
print(f"Profit factor: {summary.profit_factor}")
print(f"Total trades: {summary.total_trades}")
print(f"SL stop: {summary.sl_stop}")
print(f"SL trail: {summary.sl_trail}")
print(f"Output: {summary.output_path}")

# %% [markdown]
# ## Plot the equity curve and trades

# %%
fig = result.portfolio.plot()
fig.show()

# %% [markdown]
# ## Inspect the ATR and stop-distance series
#
# The ATR value and the converted stop fraction show how the trailing
# stop widens during volatile periods and tightens during quiet ones.

# %%
import vectorbt as vbt

atr = vbt.ATR.run(high, low, close, window=14).atr
stop_distance = signals.sl_stop

print("ATR summary:")
print(atr.describe())
print(f"\nStop distance (fraction of price) summary:")
print(stop_distance.describe())