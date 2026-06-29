"""Alpaca historical stock bars source."""

from __future__ import annotations

import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx

from trade_data.models import Bar, HistoricalBarsRequest, HistoricalBarsResult, utc_to_json
from trade_data.sessions import MarketSessionConfig, get_market_session_config
from trade_data.store import LocalMarketDataStore

ALPACA_STOCK_BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"


class AlpacaHistoricalBarsSource:
    def __init__(
        self,
        *,
        api_key_id: str,
        api_secret_key: str,
        store: LocalMarketDataStore,
        client: httpx.Client | None = None,
        base_url: str = ALPACA_STOCK_BARS_URL,
        feed: str = "sip",
        adjustment: str = "raw",
        limit: int = 10_000,
    ) -> None:
        self._api_key_id = api_key_id
        self._api_secret_key = api_secret_key
        self._store = store
        self._client = client or httpx.Client(timeout=30.0)
        self._base_url = base_url
        self._feed = feed
        self._adjustment = adjustment
        self._limit = limit

    @classmethod
    def from_env(
        cls,
        *,
        store: LocalMarketDataStore,
        client: httpx.Client | None = None,
    ) -> AlpacaHistoricalBarsSource:
        return cls(
            api_key_id=_required_env("ALPACA_API_KEY_ID"),
            api_secret_key=_required_env("ALPACA_API_SECRET_KEY"),
            store=store,
            client=client,
        )

    def get_historical_bars(
        self,
        request: HistoricalBarsRequest,
        *,
        session_config: MarketSessionConfig | None = None,
    ) -> HistoricalBarsResult:
        """Fetch provider bars, preserve raw pages, and write normalized local bars.

        Backtests should read the normalized JSONL files later. This method is the
        data-preparation step that turns Alpaca-shaped responses into project-owned
        `Bar` records.
        """
        resolved_session_config = session_config or get_market_session_config(request.market)
        safe_request = self._clip_request_end_for_free_sip(request)

        raw_pages_saved = 0
        normalized_candidates: list[Bar] = []
        page_token: str | None = None
        page_number = 1

        # Alpaca returns large ranges in pages. We keep each raw page before
        # normalization so provider payloads remain inspectable without leaking
        # Alpaca response fields into strategy-facing code.
        while True:
            payload = self._fetch_page(safe_request, page_token=page_token)
            self._store.save_alpaca_raw_page(
                safe_request,
                page_number,
                payload,
                feed=self._feed,
                adjustment=self._adjustment,
            )
            raw_pages_saved += 1
            normalized_candidates.extend(
                self._normalize_bars(
                    payload=payload,
                    request=safe_request,
                    session_config=resolved_session_config,
                )
            )
            page_token = _optional_string(payload.get("next_page_token"))
            if page_token is None:
                break
            page_number += 1

        # Session filtering happens after normalization because the normalized bar
        # carries the project session label (`regular`, `extended`, or `closed`).
        selected_bars = tuple(
            bar
            for bar in normalized_candidates
            if resolved_session_config.is_selected(bar.timestamp_utc, safe_request.session)
        )
        written_paths = self._store.save_normalized_bars(
            selected_bars,
            safe_request,
            resolved_session_config,
        )
        return HistoricalBarsResult(
            bars=tuple(sorted(selected_bars, key=lambda bar: bar.timestamp_utc)),
            raw_pages_saved=raw_pages_saved,
            normalized_files_written=len(written_paths),
            filtered_bars=len(normalized_candidates) - len(selected_bars),
        )

    def _fetch_page(
        self,
        request: HistoricalBarsRequest,
        *,
        page_token: str | None,
    ) -> dict[str, Any]:
        params: dict[str, str | int] = {
            "symbols": request.instrument.provider_symbol,
            "timeframe": request.timeframe,
            "feed": self._feed,
            "adjustment": self._adjustment,
            "start": utc_to_json(request.start_utc),
            "end": utc_to_json(request.end_utc),
            "limit": self._limit,
        }
        if page_token is not None:
            params["page_token"] = page_token

        response = self._client.get(
            self._base_url,
            params=params,
            headers={
                "APCA-API-KEY-ID": self._api_key_id,
                "APCA-API-SECRET-KEY": self._api_secret_key,
            },
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            msg = "Alpaca response must be a JSON object"
            raise ValueError(msg)
        return cast(dict[str, Any], payload)

    def _normalize_bars(
        self,
        *,
        payload: dict[str, Any],
        request: HistoricalBarsRequest,
        session_config: MarketSessionConfig,
    ) -> Iterable[Bar]:
        bars_by_symbol_value = payload.get("bars", {})
        if not isinstance(bars_by_symbol_value, dict):
            msg = "Alpaca response field 'bars' must be an object"
            raise ValueError(msg)
        bars_by_symbol = cast(dict[str, Any], bars_by_symbol_value)

        raw_bars_value = bars_by_symbol.get(request.instrument.provider_symbol, [])
        if not isinstance(raw_bars_value, list):
            msg = "Alpaca symbol bars must be a list"
            raise ValueError(msg)
        raw_bars = cast(list[Any], raw_bars_value)

        # Alpaca uses compact field names (`o`, `h`, `l`, `c`, `v`, `t`). Normalize
        # them once here so every downstream strategy/backtest sees explicit,
        # provider-neutral names and a project instrument ID like `SPY.US`.
        for raw_bar_value in raw_bars:
            if not isinstance(raw_bar_value, dict):
                msg = "Alpaca bar must be an object"
                raise ValueError(msg)
            raw_bar = cast(dict[str, Any], raw_bar_value)
            timestamp = datetime.fromisoformat(str(raw_bar["t"]).replace("Z", "+00:00"))
            yield Bar(
                instrument_id=request.instrument.instrument_id,
                timeframe=request.timeframe,
                timestamp_utc=timestamp,
                open=float(raw_bar["o"]),
                high=float(raw_bar["h"]),
                low=float(raw_bar["l"]),
                close=float(raw_bar["c"]),
                volume=int(raw_bar["v"]),
                session=session_config.classify(timestamp),
            )

    def _clip_request_end_for_free_sip(
        self,
        request: HistoricalBarsRequest,
    ) -> HistoricalBarsRequest:
        """Keep SIP historical requests safely behind Alpaca's free-data delay."""
        if self._feed != "sip":
            return request
        latest_allowed_end = datetime.now(UTC) - timedelta(minutes=15)
        if request.end_utc <= latest_allowed_end:
            return request
        return HistoricalBarsRequest(
            instrument=request.instrument,
            timeframe=request.timeframe,
            start_utc=request.start_utc,
            end_utc=latest_allowed_end,
            market=request.market,
            session=request.session,
        )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value == "":
        msg = f"missing required environment variable: {name}"
        raise RuntimeError(msg)
    return value


def _optional_string(value: object) -> str | None:
    if value is None or value == "":
        return None
    return str(value)
