"""Fetch split+dividend-adjusted daily bars for a liquid ETF universe.

Why a dedicated fetch (not the ``market-data fetch`` CLI): the CLI/``from_env``
default is ``adjustment="raw"``. A cross-asset momentum strategy ranks bond
ETFs (TLT, IEF), high-yield credit (HYG) and dividend-heavy sector/REIT ETFs
against equity. Raw prices systematically understate total return and do so
*disproportionately* for high-yield assets, which would bias every momentum
comparison. We therefore fetch ``adjustment="all"`` (split + dividend adjusted),
which gives a total-return-like series, into a SEPARATE cache root so it never
collides with the existing raw SPY store.

Alpaca free SIP daily history starts 2016-01-04; requesting earlier just returns
from that date. Output cache: ``.data/momentum_adj/`` (gitignored under .data/).

Run:
    set -a; source .env; set +a
    uv run python research/momentum/fetch_universe.py
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
CACHE_DIR = REPO_ROOT / ".data" / "momentum_adj"

# Liquid, IBKR-tradable ETFs. No penny stocks, no leverage, no options/futures.
# Grouped by role so the strategy layer can build asset-class or sector sleeves.
UNIVERSE: dict[str, list[str]] = {
    # Broad equity beta (rotation + benchmark)
    "equity": ["SPY", "QQQ", "IWM", "EFA", "EEM"],
    # GICS sector SPDRs (XLRE from 2015, XLC from 2018 — ragged start handled downstream)
    "sectors": ["XLK", "XLE", "XLF", "XLV", "XLY", "XLP", "XLI", "XLU", "XLB", "XLRE", "XLC"],
    # Bonds / defensive (SHY doubles as the cash / risk-free proxy)
    "bonds": ["TLT", "IEF", "LQD", "HYG", "SHY"],
    # Real assets
    "real": ["GLD", "VNQ", "DBC"],
    # Leveraged index ETFs + T-bill cash sleeve (trend-timed candidate only).
    # Leverage comes from the ETF, not the account — no margin used.
    "leveraged": ["QLD", "TQQQ", "SSO", "UPRO", "BIL"],
}

ALL_SYMBOLS: list[str] = [s for group in UNIVERSE.values() for s in group]

START = datetime(2016, 1, 1, tzinfo=UTC)
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
        adjustment="all",  # split + dividend adjusted => total-return-like
    )

    print(f"Fetching {len(ALL_SYMBOLS)} symbols, adjusted daily, into {CACHE_DIR}")
    for i, symbol in enumerate(ALL_SYMBOLS, 1):
        req = HistoricalBarsRequest(
            instrument=Instrument.us_equity(symbol),
            timeframe="1Day",
            start_utc=START,
            end_utc=END,
            session="all",
        )
        res = src.get_historical_bars(req)
        first = res.bars[0].timestamp_utc.date() if res.bars else None
        last = res.bars[-1].timestamp_utc.date() if res.bars else None
        print(f"[{i:2d}/{len(ALL_SYMBOLS)}] {symbol:5s} bars={len(res.bars):5d} {first} -> {last}")
        time.sleep(0.15)  # be polite to the API between symbols
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
