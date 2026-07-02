# VectorBT Backtesting

The VectorBT track is a fast-prototyping backtesting path that uses
[VectorBT](https://github.com/polakowo/vectorbt) to try new strategy ideas in a
few lines of code, without hand-coding indicators, signal arrays, or portfolio
simulation.

It is a **second track**, not a replacement of the existing bar-by-bar engine.
The existing engine stays authoritative for validated runs: it owns the
traceability chain (`StrategyRunId -> DecisionId -> RiskDecisionId ->
OrderIntentId`), next-bar-open fills with no lookahead, per-trade MFE/MAE,
R-multiple diagnostics, regime enrichment, and an 11-scenario cost-stress grid.
The VectorBT track accelerates the opposite job: trying a new idea quickly, then
reading off portfolio metrics.

| Track | Purpose | When to use |
|---|---|---|
| Existing engine | Rigorous: traceability, MFE/MAE/R, enrichment, cost-stress | Validated strategies, reproducible research artifacts |
| VectorBT track | Fast iteration: indicators, signals, portfolio metrics | Prototyping new ideas before promoting them |

A strategy that proves out in VectorBT gets promoted to the `Strategy` protocol
+ custom engine when it needs the rigorous diagnostics. The two tracks share one
normalized data seam (the `Bar` model), so promotion is a re-implementation in a
stricter form, not a re-derivation of data.

## Architecture

```
packages/trade_vectorbt/          Isolated package owning all pandas/numpy/vectorbt deps
  adapter.py                      Bar sequence  ->  OHLCV DataFrame
  signals.py                      Reference signal generators (MA, RSI, ATR)
  runner.py                       run_vectorbt_backtest()  ->  VectorbtResult
  summary.py                       build_vectorbt_summary()  ->  VectorbtSummary + JSON artifact

apps/research/.../vbt/runner.py   CLI-level runner: request -> bars -> signals -> sim -> summary
apps/research/.../cli.py           backtest vbt subcommand

notebooks/                        Example walkthrough notebooks
```

### Package boundaries

- `packages/trade_vectorbt` owns the DataFrame adapter, signal generators,
  portfolio runner, and summary extraction. Pandas, numpy, and numba are
  isolated here so the rest of the workspace stays lightweight and importable
  without them.
- `apps/research` adds a dependency on `trade_vectorbt` and gains the
  `backtest vbt` subcommand. The CLI handler is thin: argument parsing +
  output printing. The `vbt/runner.py` module owns the pandas/vectorbt
  interaction and returns a well-typed `VectorbtSummary` to the CLI.
- Pyright strict mode is relaxed only for `packages/trade_vectorbt`,
  `tests/trade_vectorbt`, and `apps/research/src/trade_research_app/vbt`
  because vectorbt/pandas ship without type stubs. The rest of the workspace
  stays fully strict.

See `docs/architecture/vectorbt-integration-plan.md` for the full dual-track
rationale, 5-phase plan, risks, and scope boundaries.

## Prepare Data

VectorBT reads from the same local normalized bar cache as the existing engine.
Fetch data first:

```sh
uv run python -m trade_research_app market-data fetch \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-01-01 \
  --end 2025-06-30 \
  --market XNYS \
  --session regular
```

The runner reads project-owned normalized JSONL partitions through
`trade_data.LocalMarketDataStore`. It does not read provider-specific raw
responses directly.

For Alpaca credentials, cache layout, and public-safety rules, see
`docs/market-data.md`.

## Run A Backtest

### Available strategies

Three reference signal generators are built in:

| Strategy | Signals | Key parameters |
|---|---|---|
| `ma-cross` | MA crossover: enter when fast crosses above slow, exit below | `--fast`, `--slow` |
| `rsi-revert` | RSI mean-reversion: enter when RSI < lower, exit when RSI > upper | `--window`, `--lower`, `--upper` |
| `atr-trail` | ATR trailing stop: always-in long with volatility-scaled trailing stop | `--window`, `--multiplier` |

These are **reference** generators: they demonstrate common patterns and are
meant to be copied or extended, not to be complete trading systems.

### Basic usage

```sh
uv run python -m trade_research_app backtest vbt \
  --strategy ma-cross \
  --symbol SPY \
  --timeframe 5Min \
  --start 2025-01-01 \
  --end 2025-06-30 \
  --fast 10 \
  --slow 30 \
  --direction longonly
```

By default, the summary is written to:

```text
.data/backtests/vbt/<strategy>/<instrument>_<timeframe>_<start>_<end>.json
```

### Example output

The CLI prints a self-describing metrics block:

```text
strategy=ma-cross
start=2025-01-01T00:00:00+00:00
end=2025-06-30T00:00:00+00:00
n_bars=19422
init_cash=10000.0
fees=0.0
slippage=0.0
direction=longonly
freq=5min
sl_stop=None
tp_stop=None
sl_trail=False
total_return=0.0588
cagr=0.1187
final_value=10588.0
sharpe_ratio=1.6423
sortino_ratio=2.3105
calmar_ratio=1.234
omega_ratio=1.45
max_drawdown=-0.0345
max_drawdown_duration_bars=142
total_trades=23
long_trades=23
short_trades=0
winning_trades=13
losing_trades=10
win_rate=0.5652
profit_factor=1.78
expectancy=25.6
best_trade_return=0.034
worst_trade_return=-0.021
output=.data/backtests/vbt/ma-cross/SPY.US_5Min_20250101T000000Z_20250630T000000Z.json
```

### All CLI options

#### Data selection

| Flag | Default | Description |
|---|---|---|
| `--strategy` | (required) | `ma-cross`, `rsi-revert`, or `atr-trail` |
| `--symbol` | (required) | Ticker symbol (e.g. `SPY`) |
| `--timeframe` | `5Min` | Bar timeframe (`1Min`, `5Min`, `15Min`, `30Min`, `1H`, `1D`) |
| `--start` | (required) | Inclusive market-local date, `YYYY-MM-DD` |
| `--end` | (required) | Inclusive market-local date, `YYYY-MM-DD` |
| `--market` | `XNYS` | Market calendar ID |
| `--session` | `regular` | `regular`, `extended`, or `all` |
| `--cache-dir` | `.data` | Root directory for the local bar cache |
| `--output` | auto | Explicit JSON summary path |

#### Simulation parameters

| Flag | Default | Description |
|---|---|---|
| `--init-cash` | `10000` | Starting cash for the simulated account |
| `--fees` | `0` | Transaction cost as a **fraction of trade value** (0.001 = 0.1%) |
| `--slippage` | `0` | One-way slippage as a fraction of price (0.001 = 0.1%) |
| `--direction` | `longonly` | `longonly`, `shortonly`, or `both` |
| `--freq` | auto | Bar frequency for annualized metrics (`5min`, `D`, etc.) |
| `--sl-stop` | None | Stop-loss as a fraction of price (0.03 = 3%) |
| `--tp-stop` | None | Take-profit as a fraction of price (0.05 = 5%) |

#### Strategy-specific parameters

These are shared across all three strategies; each strategy ignores the ones it
doesn't use. This keeps the CLI flat and avoids per-strategy subparsers for only
two or three params each.

| Flag | Default | Used by | Description |
|---|---|---|---|
| `--fast` | `10` | `ma-cross` | Fast MA window |
| `--slow` | `30` | `ma-cross` | Slow MA window |
| `--window` | `14` | `rsi-revert`, `atr-trail` | RSI/ATR lookback window |
| `--lower` | `30` | `rsi-revert` | RSI lower threshold |
| `--upper` | `70` | `rsi-revert` | RSI upper threshold |
| `--multiplier` | `2` | `atr-trail` | ATR multiplier (stop distance = ATR * multiplier) |

### Run with costs

Costs are opt-in. Defaults are zero.

```sh
uv run python -m trade_research_app backtest vbt \
  --strategy ma-cross \
  --symbol SPY \
  --start 2025-01-01 \
  --end 2025-06-30 \
  --fees 0.001 \
  --slippage 0.0005 \
  --init-cash 50000
```

**Important:** VectorBT's `fees` parameter is a **fraction of trade value**
(0.001 = 0.1%), not a per-share commission. This differs from the existing
engine's `BacktestCostModel` which uses `commission_per_share` +
`minimum_commission`. The mapping is approximate and documented in
`docs/architecture/vectorbt-integration-plan.md`.

### Run with stop-loss and take-profit

```sh
uv run python -m trade_research_app backtest vbt \
  --strategy ma-cross \
  --symbol SPY \
  --start 2025-01-01 \
  --end 2025-06-30 \
  --sl-stop 0.03 \
  --tp-stop 0.05
```

For `atr-trail`, the `--sl-stop` flag is ignored: the strategy generates its own
per-bar stop-loss Series from the ATR indicator, and `sl_trail=True` is set
automatically so the stop ratchets with the high-water mark.

## Analyze Results

### The JSON artifact

Each run writes a JSON summary to `.data/backtests/vbt/<strategy>/`. The
artifact is self-describing: it contains identity, configuration, portfolio
metrics, and trade stats.

```json
{
  "strategy_name": "ma-cross",
  "start": "2025-01-01T00:00:00+00:00",
  "end": "2025-06-30T00:00:00+00:00",
  "n_bars": 19422,
  "init_cash": "10000.0",
  "fees": "0.001",
  "slippage": "0.0005",
  "direction": "longonly",
  "freq": "5min",
  "sl_stop": "",
  "tp_stop": "",
  "sl_trail": false,
  "total_return": "0.0588",
  "cagr": "0.1187",
  "final_value": "10588.0",
  "sharpe_ratio": "1.6423",
  "sortino_ratio": "2.3105",
  "calmar_ratio": "1.234",
  "omega_ratio": "1.45",
  "max_drawdown": "-0.0345",
  "max_drawdown_duration_bars": 142,
  "total_trades": 23,
  "long_trades": 23,
  "short_trades": 0,
  "winning_trades": 13,
  "losing_trades": 10,
  "win_rate": "0.5652",
  "profit_factor": "1.78",
  "expectancy": "25.6",
  "best_trade_return": "0.034",
  "worst_trade_return": "-0.021"
}
```

### Metric definitions

#### Portfolio-level metrics

| Metric | What it means | When it's `null` |
|---|---|---|
| `total_return` | Total PnL as a fraction of initial cash | Never (0.0 for flat) |
| `cagr` | Compound annual growth rate from calendar span | Span < 1 day or total loss > 100% |
| `final_value` | Portfolio value at the end of the run | Never |
| `sharpe_ratio` | Annualized Sharpe ratio (needs `freq`) | Constant returns (no-trade) |
| `sortino_ratio` | Annualized Sortino ratio (downside-only) | Constant returns |
| `calmar_ratio` | CAGR / abs(max drawdown) | No drawdown or no trades |
| `omega_ratio` | Probability-weighted gain/loss ratio | No trades |
| `max_drawdown` | Deepest equity drop from a prior high-water mark | Never (0.0 for monotonic) |
| `max_drawdown_duration_bars` | Longest consecutive run of drawdown bars | Never (0 if no drawdown) |

#### Trade-level metrics

| Metric | What it means | When it's `null` |
|---|---|---|
| `total_trades` | Number of closed trades | Never (0 for no trades) |
| `long_trades` | Trades closed from a long position | Never |
| `short_trades` | Trades closed from a short position | Never |
| `winning_trades` | Trades with positive PnL | Never |
| `losing_trades` | Trades with negative PnL | Never |
| `win_rate` | Winning trades / total trades | No trades (NaN) |
| `profit_factor` | Sum of wins / abs(sum of losses) | No trades or no losses (NaN/Inf) |
| `expectancy` | Average PnL per trade | No trades (NaN) |
| `best_trade_return` | Highest single-trade return fraction | No trades (NaN) |
| `worst_trade_return` | Lowest single-trade return fraction | No trades (NaN) |

### NaN and Inf handling

VectorBT returns `NaN` for metrics like `win_rate` when there are no trades and
`Inf` for `sharpe_ratio` when returns are constant (e.g., a flat no-trade
portfolio). Neither is valid JSON, so the summary converts them to `null` in the
artifact. The CLI prints them as `None`.

### Number serialization

Float values are stringified with `str()` in the JSON artifact for human-readable
precision, mirroring the existing engine's `str(Decimal)` pattern. Integer values
are written as JSON numbers. Boolean values (`sl_trail`) are written as JSON
booleans.

### Reading the artifact in Python

```python
import json
from pathlib import Path

artifact = json.loads(Path(".data/backtests/vbt/ma-cross/SPY.US_5Min_...json").read_text())

# All float fields are strings for precision; convert when needed.
total_return = float(artifact["total_return"]) if artifact["total_return"] is not None else None
sharpe = float(artifact["sharpe_ratio"]) if artifact["sharpe_ratio"] is not None else None
```

## Use the Python API directly

The CLI is a thin wrapper around the `trade_vectorbt` package. For more
control — custom signal generators, multiple parameter sweeps, or access to
the raw `vbt.Portfolio` object for plotting — use the Python API directly.

### End-to-end example

```python
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

# 1. Load bars from the local cache (same data seam as the existing engine).
request = HistoricalBarsRequest(
    instrument=Instrument.us_equity("SPY"),
    timeframe="5Min",
    start_utc=pd.Timestamp("2025-01-01", tz="UTC"),
    end_utc=pd.Timestamp("2025-07-01", tz="UTC"),
)
session_config = get_market_session_config("XNYS")
store = LocalMarketDataStore(Path(".data"))
bars = store.load_bars(request, session_config)

# 2. Convert to the OHLCV DataFrame that vectorbt expects.
df = to_ohlcv_dataframe(bars)
close = df["close"]

# 3. Generate signals. Use a built-in generator or write your own.
signals = ma_cross_signals(close, fast=10, slow=30)

# 4. Run the portfolio simulation.
result = run_vectorbt_backtest(
    close,
    signals.entries,
    signals.exits,
    init_cash=10_000.0,
    fees=0.001,
    slippage=0.0005,
    direction="longonly",
    freq="5min",  # required for intraday annualized metrics
)

# 5. Inspect raw portfolio metrics directly on the vbt.Portfolio object.
print(f"Total return: {result.portfolio.total_return():.4f}")
print(f"Sharpe:       {result.portfolio.sharpe_ratio():.4f}")
print(f"Max drawdown: {result.portfolio.max_drawdown():.4f}")
print(f"Trades:       {result.portfolio.trades.count()}")

# 6. Build the summary artifact (extracts 30+ metrics, writes JSON).
summary = build_vectorbt_summary(
    result,
    strategy_name="ma-cross",
    output_path=Path(".data/backtests/vbt/ma-cross/my_run.json"),
)
```

### Write custom signal generators

The built-in generators (`ma_cross_signals`, `rsi_revert_signals`,
`atr_trail_signals`) return a `Signals` dataclass with boolean `entries` and
`exits` Series. To prototype a custom strategy, build your own signals and pass
them to `run_vectorbt_backtest`:

```python
import pandas as pd
import vectorbt as vbt

from trade_vectorbt import Signals, run_vectorbt_backtest

# Example: Bollinger Band mean-reversion
close = df["close"]
bb = vbt.BBANDS.run(close, window=20, alpha=2.0)

entries = close < bb.lower_bb   # price below lower band -> buy
exits = close > bb.upper_bb     # price above upper band -> exit

signals = Signals(entries=entries, exits=exits)

result = run_vectorbt_backtest(
    close,
    signals.entries,
    signals.exits,
    init_cash=10_000.0,
    fees=0.001,
    direction="longonly",
    freq="5min",
)
```

The `Signals` dataclass has three fields:

| Field | Type | Description |
|---|---|---|
| `entries` | `pd.Series[bool]` | True on bars where a new position should open |
| `exits` | `pd.Series[bool]` | True on bars where an open position should close |
| `sl_stop` | `pd.Series[float] | None` | Per-bar stop-loss as a fraction of price (for ATR-style stops) |

### Access the raw portfolio object

The `VectorbtResult.portfolio` field holds the raw `vbt.Portfolio` object. Use
it for plotting and metrics that aren't in the summary:

```python
# Equity curve
fig = result.portfolio.plot()
fig.show()

# Trade markers on the price chart
fig = result.portfolio.trades.plot()
fig.show()

# Drawdown series
drawdown = result.portfolio.drawdown()
print(drawdown.describe())

# Full trade records as a DataFrame
trades_df = result.portfolio.trades.records_readable
print(trades_df[["Direction", "PnL", "Return"]].head())
```

Plotting requires `plotly`, which is installed with vectorbt.

## Execution Semantics

### Fill timing

VectorBT fills at the **signal bar by default**. The existing engine fills at
the **next bar open** with no lookahead, plus supports explicit `@price`
same-bar fills.

This divergence is acceptable for prototyping but means results from the two
tracks are **not directly comparable** without accounting for fill timing. A
vectorbt run will generally look slightly better than the equivalent custom
engine run for the same signals because the signal-bar fill is one bar earlier.

### Cost model mapping

| Track | Fees | Slippage |
|---|---|---|
| Existing engine | Per-share commission + minimum | Basis points (bps) of fill price |
| VectorBT | Fraction of trade value (0.001 = 0.1%) | Fraction of price (0.001 = 0.1%) |

The mapping is approximate. A per-share commission of $0.005 on a $100 stock is
0.005% of trade value, so the approximate vectorbt `fees` equivalent is
`0.00005`. For research decisions, always cross-validate on the existing
engine's cost-stress grid before promoting a strategy.

### Frequency and annualized metrics

VectorBT infers the bar frequency from the index, but **intraday data with
session gaps breaks this inference**. The CLI auto-resolves `freq` from the
`--timeframe` flag:

| Timeframe | Pandas freq |
|---|---|
| `1Min` | `1min` |
| `5Min` | `5min` |
| `15Min` | `15min` |
| `30Min` | `30min` |
| `1H` | `1h` |
| `1D` | `D` |

Override with `--freq` if you need a custom frequency. When using the Python
API directly, always pass `freq=` for intraday data.

### Direction modes

| Direction | Behavior |
|---|---|
| `longonly` | Entry opens long; exit closes long |
| `shortonly` | Entry opens short; exit closes short |
| `both` | Entry opens long; exit flips to short (long/short) |

Most mean-reversion strategies pair best with `longonly`. Trend-following
strategies can use `both` for a always-in-market long/short flip.

## Notebooks

Three example notebooks in `notebooks/` demonstrate the full workflow:

| Notebook | Strategy | What it covers |
|---|---|---|
| `01_ma_crossover.py` | MA crossover | Load data, generate signals, run, build summary, plot equity curve + trades |
| `02_rsi_mean_reversion.py` | RSI mean-reversion | RSI overlay, mean-reversion signals, portfolio plot |
| `03_atr_trailing_stop.py` | ATR trailing stop | ATR stop-distance inspection, trailing-stop simulation |

Each notebook is runnable with or without pre-fetched data. When no cached bars
are found, synthetic data is generated so the notebook is always executable.

Run a notebook:

```sh
uv run jupyter lab notebooks/01_ma_crossover.py
```

Or execute as a script:

```sh
uv run python notebooks/01_ma_crossover.py
```

## Promotion Path

When a vectorbt-validated strategy shows promise, promote it to the rigorous
engine:

1. **Validate in vectorbt**: Run the strategy across a meaningful date range
   with realistic costs. Check Sharpe, max drawdown, win rate, profit factor.
2. **Implement as a `Strategy` protocol class**: Re-implement the signal logic
   as a `Strategy`-protocol class in `packages/trade_strategies/`. The `Bar`
   model is shared, so data access is identical — only the decision logic
   changes.
3. **Register in the strategy registry**: Add the factory in
   `trade_strategies.registry` so it's runnable from `backtest run`.
4. **Run the full diagnostic suite**: The existing engine adds traceability
   (StrategyRunId -> DecisionId -> OrderIntentId), next-bar-open fills,
   per-trade MFE/MAE, R-multiple diagnostics, regime enrichment, and the
   11-scenario cost-stress grid.
5. **Compare results**: The two tracks' PnL won't match exactly due to fill
   timing divergence. Focus on whether the *edge* persists: does the strategy
   still have positive costed expectancy, acceptable profit factor, and
   manageable drawdown under the stricter fill model?

The promotion path is documented in detail in
`docs/architecture/vectorbt-promotion-path.md` (Phase 5).

## Limitations

- **Fill timing**: vectorbt fills at the signal bar, not next-bar-open. Results
  are not directly comparable to the existing engine.
- **Order types**: vectorbt Community edition lacks limit/stop/partial-fill
  modeling. `from_signals` supports `sl_stop`, `tp_stop`, and `sl_trail`, so
  trailing-stop and bracket prototypes are expressible; exact limit-order
  semantics are not.
- **Memory**: vectorbt recommends datasets under ~200 MB. Multi-year sweeps
  need chunking and caching.
- **No traceability**: vectorbt runs don't produce StrategyRunId, DecisionId, or
  OrderIntentId chains. The summary artifact is a metrics snapshot, not an
  audit trail.
- **No MFE/MAE/R diagnostics**: vectorbt's trade records don't include
  maximum-favorable-excursion, maximum-adverse-excursion, or R-multiple
  analysis. These remain owned by the existing engine.
- **No regime enrichment**: vectorbt runs don't tag trades with gap buckets,
  opening-range state, daily trend, or relative volume. These enrichment
  dimensions are owned by the existing engine.

## Public Safety

- VectorBT artifacts under `.data/backtests/vbt/` are local artifacts and must
  not be committed.
- Keep raw result narratives, candidate verdicts, and experiment history in
  `docs/research/`.
- For the operator runbook of the existing backtesting CLI, see
  `docs/backtesting.md`.
- For the research workflow and artifact organization rules, see
  `docs/research-workflow.md` and `docs/research-artifacts.md`.