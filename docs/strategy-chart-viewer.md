# Strategy Chart Viewer

A self-contained HTML page that renders any strategy's backtest as an interactive candlestick chart with trade markers overlaid, using TradingView Lightweight Charts.

## Location

| File | Purpose |
|---|---|
| `apps/research/chart_viewer/generate.py` | Generator: reads cached bars, runs the strategy, embeds everything into a standalone HTML file |
| `apps/research/chart_viewer/chart_viewer.html` | Generated output (gitignored) |

## How to Use

```sh
uv run python3 apps/research/chart_viewer/generate.py
```

Opens the chart in your default browser.

## What You See

- **Candlesticks**: 5Min bars, NY exchange hours (9:30–16:00)
- **Green arrows** (below bar): long entry
- **Red arrows** (above bar): short entry
- **Colored squares** (above bar): exit — green if profitable, red if loss
- **Volume**: green/red histogram below price (toggle with checkbox)
- **Stats bar**: bar count, trade count, win rate, total PnL

Times are shown in New York exchange time.

## Config

Edit the constants at the top of `generate.py`:

```python
INSTRUMENT_SYMBOL = "SPY"
TIMEFRAME = "5Min"
STRATEGY_NAME = "spy-opening-range-breakout-trend-hold-midpoint-stop-max-1"
START = date(2025, 7, 1)
END = date(2026, 6, 26)
```

## How It Works

1. Loads cached normalized bars from `.data/market_data/`
2. Runs the strategy bar-by-bar to collect entry/exit decisions
3. Embeds bars + trade markers as JSON in an HTML page with Lightweight Charts
4. Opens in browser — no server required

## Dependencies

- Lightweight Charts 4.x (loaded from CDN)
- Cached market data in `.data/market_data/`
