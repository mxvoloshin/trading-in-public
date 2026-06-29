"""Local gitignored market data store."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from trade_data.models import Bar, HistoricalBarsRequest
from trade_data.sessions import MarketSessionConfig, get_market_session_config


class LocalMarketDataStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def save_alpaca_raw_page(
        self,
        request: HistoricalBarsRequest,
        page_number: int,
        payload: dict[str, Any],
        *,
        feed: str,
        adjustment: str,
    ) -> Path:
        """Persist the exact provider response for audit/debugging.

        Raw files stay under `.data/` and are not strategy inputs. They are useful
        when an Alpaca response shape changes or a normalization bug needs evidence.
        """
        path = self._alpaca_raw_page_path(
            request=request,
            page_number=page_number,
            feed=feed,
            adjustment=adjustment,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return path

    def save_normalized_bars(
        self,
        bars: Iterable[Bar],
        request: HistoricalBarsRequest,
        session_config: MarketSessionConfig,
    ) -> tuple[Path, ...]:
        """Write provider-neutral bars as daily JSONL partitions.

        Daily files make repeated backtests cheap to load while avoiding a database
        until the project proves it needs one.
        """
        bars_by_path: dict[Path, list[Bar]] = defaultdict(list)
        for bar in bars:
            local_date = session_config.local_date_for(bar.timestamp_utc)
            path = self.normalized_bars_path(request=request, local_date=local_date)
            bars_by_path[path].append(bar)

        written_paths: list[Path] = []
        for path, new_bars in bars_by_path.items():
            existing_bars = self._read_bars_file(path)
            # Re-fetching overlapping date ranges should not duplicate bars. The
            # timestamp is the natural key for one instrument/timeframe stream.
            merged_by_key = {
                (bar.instrument_id, bar.timeframe, bar.timestamp_utc): bar
                for bar in (*existing_bars, *new_bars)
            }
            merged_bars = sorted(merged_by_key.values(), key=lambda bar: bar.timestamp_utc)
            path.parent.mkdir(parents=True, exist_ok=True)
            serialized = "\n".join(
                json.dumps(bar.to_json_dict(), sort_keys=True) for bar in merged_bars
            )
            path.write_text(serialized + "\n", encoding="utf-8")
            written_paths.append(path)

        return tuple(sorted(written_paths))

    def load_bars(
        self,
        request: HistoricalBarsRequest,
        session_config: MarketSessionConfig,
    ) -> tuple[Bar, ...]:
        bars: list[Bar] = []
        for local_date in self._local_dates_for_request(request, session_config):
            path = self.normalized_bars_path(request=request, local_date=local_date)
            for bar in self._read_bars_file(path):
                if request.start_utc <= bar.timestamp_utc < request.end_utc:
                    bars.append(bar)
        return tuple(sorted(bars, key=lambda bar: bar.timestamp_utc))

    def normalized_bars_path(self, request: HistoricalBarsRequest, local_date: date) -> Path:
        return (
            self.root
            / "market_data"
            / "bars"
            / request.instrument.instrument_id
            / request.timeframe
            / request.market
            / request.session
            / f"{local_date.isoformat()}.jsonl"
        )

    def _alpaca_raw_page_path(
        self,
        request: HistoricalBarsRequest,
        page_number: int,
        feed: str,
        adjustment: str,
    ) -> Path:
        session_config = get_market_session_config(request.market)
        # CLI dates are market-local and inclusive, while requests are UTC and
        # end-exclusive. Use market-local dates here so filenames match what the
        # user asked for instead of showing the next UTC date after market close.
        start = session_config.local_date_for(request.start_utc).isoformat()
        end = session_config.local_date_for(request.end_utc - timedelta(microseconds=1)).isoformat()
        filename = f"{start}_{end}_feed-{feed}_adjustment-{adjustment}_page-{page_number:03d}.json"
        return (
            self.root
            / "alpaca"
            / "stock_bars"
            / request.instrument.provider_symbol
            / request.timeframe
            / "raw"
            / filename
        )

    def _read_bars_file(self, path: Path) -> tuple[Bar, ...]:
        if not path.exists():
            return ()
        bars = [
            Bar.from_json_dict(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return tuple(bars)

    def _local_dates_for_request(
        self,
        request: HistoricalBarsRequest,
        session_config: MarketSessionConfig,
    ) -> Iterable[date]:
        current = session_config.local_date_for(request.start_utc)
        end = session_config.local_date_for(request.end_utc)
        while current <= end:
            yield current
            current += timedelta(days=1)
