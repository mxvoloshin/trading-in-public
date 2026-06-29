from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from trade_data import Bar, HistoricalBarsRequest, Instrument, LocalMarketDataStore
from trade_data.sessions import MarketSessionConfig


def test_store_writes_daily_partitions_by_market_date(tmp_path: Path) -> None:
    store = LocalMarketDataStore(tmp_path)
    session_config = MarketSessionConfig.xnys_regular()
    request = HistoricalBarsRequest(
        instrument=Instrument.us_equity("SPY"),
        timeframe="5Min",
        start_utc=datetime(2026, 6, 26, 0, 0, tzinfo=UTC),
        end_utc=datetime(2026, 6, 28, 0, 0, tzinfo=UTC),
    )
    bars = (
        Bar(
            instrument_id="SPY.US",
            timeframe="5Min",
            timestamp_utc=datetime(2026, 6, 26, 13, 30, tzinfo=UTC),
            open=100.0,
            high=101.0,
            low=99.0,
            close=100.5,
            volume=1_000,
            session="regular",
        ),
        Bar(
            instrument_id="SPY.US",
            timeframe="5Min",
            timestamp_utc=datetime(2026, 6, 27, 13, 30, tzinfo=UTC),
            open=101.0,
            high=102.0,
            low=100.0,
            close=101.5,
            volume=1_100,
            session="regular",
        ),
    )

    written_paths = store.save_normalized_bars(bars, request, session_config)

    assert [path.name for path in written_paths] == ["2026-06-26.jsonl", "2026-06-27.jsonl"]
    loaded_bars = store.load_bars(request, session_config)
    assert [bar.close for bar in loaded_bars] == [100.5, 101.5]


def test_xnys_session_config_classifies_regular_extended_and_closed() -> None:
    session_config = MarketSessionConfig.xnys_regular()

    assert session_config.classify(datetime(2026, 6, 26, 13, 30, tzinfo=UTC)) == "regular"
    assert session_config.classify(datetime(2026, 6, 26, 12, 30, tzinfo=UTC)) == "extended"
    assert session_config.classify(datetime(2026, 6, 27, 13, 30, tzinfo=UTC)) == "closed"
