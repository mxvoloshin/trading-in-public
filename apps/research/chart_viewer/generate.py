"""Generate a self-contained HTML page with SPY bars + ORB trade overlays.

Usage:
    uv run python3 apps/research/chart_viewer/generate.py

Opens ``chart_viewer.html`` in the browser after generation.
"""

from __future__ import annotations

import json
import subprocess
import webbrowser
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from trade_core import DecisionAction, InstrumentRef, StrategyInputRef, StrategyRunId
from trade_strategies import StrategyDecisionContext
from trade_data import Bar, Instrument, HistoricalBarsRequest, LocalMarketDataStore
from trade_data.sessions import get_market_session_config
from trade_strategies import get_strategy
from trade_research_app.backtest.cli_wiring import bar_close_time

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
INSTRUMENT_SYMBOL = "SPY"
INSTRUMENT_MARKET = "XNYS"
TIMEFRAME = "5Min"
SESSION = "regular"
STRATEGY_NAME = "spy-opening-range-breakout-trend-hold-midpoint-stop-max-1"
START = date(2025, 7, 1)
END = date(2026, 6, 26)

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "chart_viewer.html"

NEW_YORK = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def utc_to_ny_timestamp(utc_dt: datetime) -> int:
    """Convert a UTC datetime to a NY-wall-clock Unix timestamp.

    The chart always shows NY exchange hours (9:30-16:00) regardless of
    the viewer's browser timezone.
    """
    ny_dt = utc_dt.astimezone(NEW_YORK)
    fake_utc = datetime(
        ny_dt.year, ny_dt.month, ny_dt.day,
        ny_dt.hour, ny_dt.minute, tzinfo=UTC,
    )
    return int(fake_utc.timestamp())


def inclusive_local_dates_to_utc_range(
    start_date: date, end_date: date, timezone: str
) -> tuple[datetime, datetime]:
    zone = ZoneInfo(timezone)
    start_local = datetime.combine(start_date, time.min, tzinfo=zone)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    instrument = Instrument.us_equity(symbol=INSTRUMENT_SYMBOL, market=INSTRUMENT_MARKET)
    session_config = get_market_session_config(INSTRUMENT_MARKET)
    start_utc, end_utc = inclusive_local_dates_to_utc_range(START, END, session_config.timezone)

    request = HistoricalBarsRequest(
        instrument=instrument,
        timeframe=TIMEFRAME,
        start_utc=start_utc,
        end_utc=end_utc,
        market=INSTRUMENT_MARKET,
        session=SESSION,
    )
    store = LocalMarketDataStore(Path(".data"))
    bars = store.load_bars(request, session_config)

    strategy = get_strategy(STRATEGY_NAME)
    run_id = StrategyRunId("chart-viewer")

    bar_data: list[dict] = []
    trades: list[dict] = []
    position_qty = Decimal("0")
    avg_entry = Decimal("0")
    previous_bar: Bar | None = None
    current_trade: dict | None = None

    for seq, bar in enumerate(bars, start=1):
        ts = utc_to_ny_timestamp(bar.timestamp_utc)
        bar_data.append({
            "t": ts, "o": float(bar.open), "h": float(bar.high),
            "l": float(bar.low), "c": float(bar.close), "v": int(bar.volume),
        })

        observed_at_utc = bar_close_time(bar.timeframe, bar.timestamp_utc)
        input_ref = StrategyInputRef(
            instrument=InstrumentRef(
                instrument_id=bar.instrument_id, market=INSTRUMENT_MARKET, currency="USD",
            ),
            timeframe=bar.timeframe,
            source="chart-viewer",
            observed_at_utc=observed_at_utc,
        )
        context = StrategyDecisionContext(
            strategy_run_id=run_id,
            input_ref=input_ref,
            sequence_number=seq,
            previous_bar=previous_bar,
            position_quantity=position_qty,
            average_entry_price=avg_entry,
        )
        decision = strategy.decide(bar=bar, context=context)
        previous_bar = bar

        action = decision.action
        if action == DecisionAction.ENTER_LONG:
            position_qty = Decimal("1")
            avg_entry = Decimal(str(bar.close))
            current_trade = {"et": ts, "ep": float(bar.close), "s": "L"}
        elif action == DecisionAction.ENTER_SHORT:
            position_qty = Decimal("-1")
            avg_entry = Decimal(str(bar.close))
            current_trade = {"et": ts, "ep": float(bar.close), "s": "S"}
        elif action in (DecisionAction.EXIT_LONG, DecisionAction.EXIT_SHORT) and current_trade:
            current_trade["xt"] = ts
            current_trade["xp"] = float(bar.open)
            trades.append(current_trade)
            current_trade = None
            position_qty = Decimal("0")
            avg_entry = Decimal("0")

    if current_trade:
        current_trade["xt"] = bar_data[-1]["t"]
        current_trade["xp"] = bar_data[-1]["c"]
        trades.append(current_trade)

    data_json = json.dumps({"bars": bar_data, "trades": trades}, separators=(",", ":"))

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SPY ORB Backtest</title>
<script src="https://unpkg.com/lightweight-charts@4.2.1/dist/lightweight-charts.standalone.production.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #1a1a2e; color: #e0e0e0; font-family: system-ui, -apple-system, sans-serif; padding: 16px; }}
#chart {{ width: 100%; height: 80vh; border-radius: 8px; overflow: hidden; }}
h1 {{ font-size: 1.1rem; font-weight: 500; margin-bottom: 8px; color: #ccc; }}
.controls {{ margin-bottom: 8px; display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }}
.controls label {{ font-size: 0.8rem; color: #999; }}
.controls input, .controls button {{ font-size: 0.8rem; padding: 4px 8px; border: 1px solid #333; border-radius: 4px; background: #16213e; color: #ccc; }}
.controls button {{ cursor: pointer; background: #0f3460; }}
.controls button:hover {{ background: #1a5276; }}
#stats {{ font-size: 0.75rem; color: #888; margin-top: 6px; }}
</style>
</head>
<body>
<h1>SPY 5Min · ORB Midpoint Stop Max 1 · <span id="rangeLabel"></span> <span style="font-weight:400;color:#666;font-size:0.85rem">(NY time)</span></h1>
<div class="controls">
  <button id="resetZoom">Reset Zoom</button>
  <label><input type="checkbox" id="showTrades" checked> Show trades</label>
  <label><input type="checkbox" id="showVolume" checked> Volume</label>
</div>
<div id="chart"></div>
<div id="stats">Rendering…</div>
<script>
const DATA = {data_json};

const chart = LightweightCharts.createChart(document.getElementById('chart'), {{
  layout: {{
    background: {{ color: '#1a1a2e' }},
    textColor: '#888',
    fontSize: 11,
  }},
  grid: {{
    vertLines: {{ color: '#2a2a3e' }},
    horzLines: {{ color: '#2a2a3e' }},
  }},
  timeScale: {{
    timeVisible: true,
    secondsVisible: false,
    borderColor: '#333',
  }},
  rightPriceScale: {{
    borderColor: '#333',
    scaleMargins: {{ top: 0.05, bottom: 0.25 }},
  }},
  crosshair: {{
    mode: LightweightCharts.CrosshairMode.Normal,
  }},
}});

const cs = chart.addCandlestickSeries({{
  upColor: '#26a69a',
  downColor: '#ef5350',
  borderUpColor: '#26a69a',
  borderDownColor: '#ef5350',
  wickUpColor: '#26a69a',
  wickDownColor: '#ef5350',
}});

const vs = chart.addHistogramSeries({{
  priceFormat: {{ type: 'volume' }},
  priceScaleId: 'volume',
  color: '#2a2a5e',
}});
chart.priceScale('volume').applyOptions({{
  scaleMargins: {{ top: 0.8, bottom: 0 }},
}});

function render() {{
  const bars = DATA.bars;
  const trades = DATA.trades;
  const showTrades = document.getElementById('showTrades').checked;
  const showVolume = document.getElementById('showVolume').checked;

  cs.setData(bars.map(b => ({{
    time: b.t, open: b.o, high: b.h, low: b.l, close: b.c,
  }})));

  if (showVolume) {{
  vs.setData(bars.map(b => ({{
    time: b.t, value: b.v,
    color: b.c >= b.o ? '#26a69a' : '#ef5350',
  }})));

    vs.applyOptions({{ visible: true }});
  }} else {{
    vs.setData([]);
    vs.applyOptions({{ visible: false }});
  }}

  if (showTrades) {{
    const markers = [];
    for (const t of trades) {{
      const isLong = t.s === 'L';
      const entryColor = isLong ? '#26a69a' : '#ef5350';
      markers.push({{
        time: t.et,
        position: isLong ? 'belowBar' : 'aboveBar',
        color: entryColor,
        shape: isLong ? 'arrowUp' : 'arrowDown',
        text: `ENTRY ${{isLong ? 'LONG' : 'SHORT'}} @ ${{t.ep}}`,
      }});
      if (t.xt) {{
        const pnl = isLong ? t.xp - t.ep : t.ep - t.xp;
        markers.push({{
          time: t.xt,
          position: 'aboveBar',
          color: pnl >= 0 ? '#26a69a' : '#ef5350',
          shape: 'square',
          text: `EXIT @ ${{t.xp}} (${{pnl >= 0 ? '+' : ''}}${{pnl.toFixed(2)}})`,
        }});
      }}
    }}
    cs.setMarkers(markers)
  }} else {{
    cs.setMarkers([]);
  }}

  const closed = trades.filter(t => t.xt);
  const wins = closed.filter(t => t.s === 'L' ? t.xp > t.ep : t.xp < t.ep);
  const totalPnl = closed.reduce((s, t) => s + (t.s === 'L' ? t.xp - t.ep : t.ep - t.xp), 0);
  document.getElementById('stats').textContent =
    `${{bars.length}} bars · ${{closed.length}} trades · ${{wins.length}} wins (${{closed.length ? (wins.length/closed.length*100).toFixed(0) : 0}}%) · Total PnL $${{totalPnl.toFixed(2)}}`;
}}

function tsToDate(ts) {{
  const d = new Date(ts * 1000);
  return d.toISOString().slice(0, 7);
}}

const firstBar = DATA.bars[0];
const lastBar = DATA.bars[DATA.bars.length - 1];
if (firstBar && lastBar) {{
  document.getElementById('rangeLabel').textContent =
    `${{tsToDate(firstBar.t)}} – ${{tsToDate(lastBar.t)}}`;
}}

document.getElementById('showTrades').addEventListener('change', render);
document.getElementById('showVolume').addEventListener('change', render);
document.getElementById('resetZoom').addEventListener('click', () => chart.timeScale().fitContent());

render();
chart.timeScale().fitContent();
</script>
</body>
</html>'''

    OUTPUT.write_text(html)
    print(f"Written {len(html)} bytes to {OUTPUT}")

    # Open in browser
    try:
        webbrowser.open(OUTPUT.as_uri())
    except Exception:
        subprocess.run(["open", str(OUTPUT)], check=False)


if __name__ == "__main__":
    main()
