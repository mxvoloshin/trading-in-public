from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
from trade_data import AlpacaHistoricalBarsSource, HistoricalBarsRequest, Instrument
from trade_data.sessions import MarketSessionConfig
from trade_data.store import LocalMarketDataStore


def test_alpaca_source_fetches_paginated_bars_and_writes_cache(tmp_path: Path) -> None:
    seen_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        page_token = request.url.params.get("page_token")
        if page_token is None:
            return httpx.Response(
                200,
                json={
                    "bars": {
                        "SPY": [
                            {
                                "t": "2026-06-26T13:30:00Z",
                                "o": 100.0,
                                "h": 101.0,
                                "l": 99.5,
                                "c": 100.5,
                                "v": 1234,
                            },
                            {
                                "t": "2026-06-26T12:30:00Z",
                                "o": 98.0,
                                "h": 99.0,
                                "l": 97.5,
                                "c": 98.5,
                                "v": 1000,
                            },
                        ]
                    },
                    "next_page_token": "next-page",
                },
            )
        return httpx.Response(
            200,
            json={
                "bars": {
                    "SPY": [
                        {
                            "t": "2026-06-26T13:35:00Z",
                            "o": 100.5,
                            "h": 101.5,
                            "l": 100.0,
                            "c": 101.0,
                            "v": 1500,
                        }
                    ]
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = LocalMarketDataStore(tmp_path)
    source = AlpacaHistoricalBarsSource(
        api_key_id="key",
        api_secret_key="secret",
        store=store,
        client=client,
    )
    request = HistoricalBarsRequest(
        instrument=Instrument.us_equity("SPY"),
        timeframe="5Min",
        start_utc=datetime(2026, 6, 26, 4, 0, tzinfo=UTC),
        end_utc=datetime(2026, 6, 27, 4, 0, tzinfo=UTC),
    )

    result = source.get_historical_bars(request)

    assert result.raw_pages_saved == 2
    assert result.filtered_bars == 1
    assert [bar.timestamp_utc.isoformat() for bar in result.bars] == [
        "2026-06-26T13:30:00+00:00",
        "2026-06-26T13:35:00+00:00",
    ]
    assert seen_requests[0].url.params["symbols"] == "SPY"
    assert seen_requests[0].url.params["timeframe"] == "5Min"
    assert seen_requests[0].url.params["feed"] == "sip"
    assert seen_requests[0].url.params["adjustment"] == "raw"
    assert seen_requests[0].headers["APCA-API-KEY-ID"] == "key"
    assert seen_requests[1].url.params["page_token"] == "next-page"

    raw_pages = sorted(tmp_path.glob("alpaca/stock_bars/SPY/5Min/raw/*.json"))
    assert [path.name for path in raw_pages] == [
        "2026-06-26_2026-06-26_feed-sip_adjustment-raw_page-001.json",
        "2026-06-26_2026-06-26_feed-sip_adjustment-raw_page-002.json",
    ]

    normalized_files = sorted(tmp_path.glob("market_data/bars/SPY.US/5Min/XNYS/regular/*.jsonl"))
    assert [path.name for path in normalized_files] == ["2026-06-26.jsonl"]
    assert len(normalized_files[0].read_text(encoding="utf-8").splitlines()) == 2


def test_alpaca_source_deduplicates_overlapping_normalized_fetches(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "bars": {
                    "SPY": [
                        {
                            "t": "2026-06-26T13:30:00Z",
                            "o": 100.0,
                            "h": 101.0,
                            "l": 99.5,
                            "c": 100.5,
                            "v": 1234,
                        }
                    ]
                }
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    store = LocalMarketDataStore(tmp_path)
    source = AlpacaHistoricalBarsSource(
        api_key_id="key",
        api_secret_key="secret",
        store=store,
        client=client,
    )
    request = HistoricalBarsRequest(
        instrument=Instrument.us_equity("SPY"),
        timeframe="5Min",
        start_utc=datetime(2026, 6, 26, 4, 0, tzinfo=UTC),
        end_utc=datetime(2026, 6, 27, 4, 0, tzinfo=UTC),
    )

    source.get_historical_bars(request)
    source.get_historical_bars(request)

    bars = store.load_bars(request, session_config=source_session_config())
    assert len(bars) == 1


def source_session_config() -> MarketSessionConfig:
    return MarketSessionConfig.xnys_regular()
