"""Fetch split+dividend-adjusted daily bars for a liquid large-cap STOCK universe.

Prior research tracks all traded index/sector ETFs (SPY, sector SPDRs). This track
tests *individual stocks*, where the cross-sectional momentum factor is far stronger
than at the sector level. We fetch ``adjustment="all"`` (split + dividend adjusted,
total-return-like) into a SEPARATE cache root so it never collides with the raw SPY
store or the ETF momentum cache.

Survivorship / selection-bias note (disclosed, not hidden): the universe below is a
broad set of large/mega-cap US names that were already large and liquid in early
2020. Picking "names that are big today" tilts results upward. We mitigate — but do
not eliminate — this by (a) using a large, sector-diversified set rather than a
hand-picked winners list, (b) requiring a full lookback of history before a name is
eligible, (c) train/test splitting, and (d) benchmarking against SPY/QQQ. Treat the
absolute numbers as directional; the robustness gates matter more than the headline.

Window: 2019-06 → now. The strategy only trades from 2020 onward (per the study
constraint) but we fetch a short warmup tail so the first 2020 momentum lookback has
history. Alpaca free SIP daily history is available from 2016.

Run:
    set -a; source .env; set +a
    uv run python research/stocks/fetch_stocks.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from trade_data import HistoricalBarsRequest, Instrument, LocalMarketDataStore
from trade_data.alpaca import AlpacaHistoricalBarsSource

REPO_ROOT = Path(__file__).resolve().parents[2]
CACHE_DIR = REPO_ROOT / ".data" / "stocks_adj"

# Broad, sector-diversified large/mega-cap universe, all liquid and public in early
# 2020. Grouped only for readability; the strategy ranks them as one flat universe.
UNIVERSE: dict[str, list[str]] = {
    "mega_tech": [
        "AAPL",
        "MSFT",
        "GOOGL",
        "AMZN",
        "META",
        "NVDA",
        "AVGO",
        "ADBE",
        "CRM",
        "ORCL",
        "CSCO",
        "INTC",
        "AMD",
        "QCOM",
        "TXN",
        "IBM",
    ],
    "consumer": [
        "TSLA",
        "HD",
        "NKE",
        "MCD",
        "SBUX",
        "LOW",
        "TGT",
        "COST",
        "WMT",
        "PG",
        "KO",
        "PEP",
        "PM",
        "MDLZ",
        "CL",
    ],
    "health": [
        "UNH",
        "JNJ",
        "LLY",
        "PFE",
        "MRK",
        "ABBV",
        "TMO",
        "ABT",
        "DHR",
        "BMY",
        "AMGN",
        "GILD",
        "CVS",
        "ISRG",
    ],
    "financials": [
        "JPM",
        "BAC",
        "WFC",
        "GS",
        "MS",
        "C",
        "AXP",
        "BLK",
        "SCHW",
        "SPGI",
        "V",
        "MA",
        "PYPL",
    ],
    "industrial_energy": [
        "BA",
        "CAT",
        "DE",
        "HON",
        "GE",
        "UPS",
        "UNP",
        "LMT",
        "RTX",
        "XOM",
        "CVX",
        "COP",
        "SLB",
    ],
    "other": ["DIS", "NFLX", "CMCSA", "T", "VZ", "LIN", "NEE", "AMT"],
    # SPY held here too so the study can build a market-trend filter from one cache.
    "bench": ["SPY", "QQQ"],
}

ALL_SYMBOLS: list[str] = sorted({s for group in UNIVERSE.values() for s in group})

# Fetch a short warmup tail before 2020 so the first 2020 momentum lookback is valid.
START = datetime(2019, 6, 1, tzinfo=UTC)
END = datetime(2026, 7, 2, tzinfo=UTC)


def main() -> int:
    key = os.environ.get("ALPACA_API_KEY_ID")
    secret = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key or not secret:
        print("ERROR: set ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY (source .env)", file=sys.stderr)
        return 1

    store = LocalMarketDataStore(CACHE_DIR)
    src = AlpacaHistoricalBarsSource(
        api_key_id=key,
        api_secret_key=secret,
        store=store,
        adjustment="all",  # split + dividend adjusted => total-return-like series
    )

    print(f"Fetching {len(ALL_SYMBOLS)} stock symbols, adjusted daily, into {CACHE_DIR}")
    failures: list[str] = []
    for i, symbol in enumerate(ALL_SYMBOLS, 1):
        req = HistoricalBarsRequest(
            instrument=Instrument.us_equity(symbol),
            timeframe="1Day",
            start_utc=START,
            end_utc=END,
            session="all",
        )
        try:
            res = src.get_historical_bars(req)
        except Exception as exc:  # noqa: BLE001 - report and continue, don't abort whole fetch
            print(f"[{i:2d}/{len(ALL_SYMBOLS)}] {symbol:6s} FAILED: {exc}")
            failures.append(symbol)
            continue
        first = res.bars[0].timestamp_utc.date() if res.bars else None
        last = res.bars[-1].timestamp_utc.date() if res.bars else None
        print(f"[{i:2d}/{len(ALL_SYMBOLS)}] {symbol:6s} bars={len(res.bars):5d} {first} -> {last}")
        time.sleep(0.12)  # be polite to the API between symbols
    if failures:
        print(f"Done with {len(failures)} failures: {', '.join(failures)}")
    else:
        print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
