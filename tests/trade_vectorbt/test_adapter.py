from __future__ import annotations

from datetime import UTC, datetime

from trade_data import Bar
from trade_vectorbt import to_ohlcv_dataframe


def _bar(
    ts: datetime,
    close: float,
    o: float | None = None,
    h: float | None = None,
    low_price: float | None = None,
    vol: int = 100,
) -> Bar:
    return Bar(
        instrument_id="SPY.US",
        timeframe="5Min",
        timestamp_utc=ts,
        open=o if o is not None else close,
        high=h if h is not None else close,
        low=low_price if low_price is not None else close,
        close=close,
        volume=vol,
        session="regular",
    )


def test_to_ohlcv_dataframe_builds_expected_columns_and_index() -> None:
    bars = [
        _bar(
            datetime(2025, 1, 1, 9, 30, tzinfo=UTC), 100.0, o=99.0, h=101.0, low_price=98.0, vol=500
        ),
        _bar(
            datetime(2025, 1, 1, 9, 35, tzinfo=UTC),
            101.0,
            o=100.5,
            h=102.0,
            low_price=100.0,
            vol=600,
        ),
    ]
    df = to_ohlcv_dataframe(bars)
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "timestamp_utc"
    assert df.index.tz is not None
    assert str(df.index.tz) == "UTC"
    assert df.loc[df.index[0], "close"] == 100.0
    assert df.loc[df.index[1], "volume"] == 600
    assert len(df) == 2


def test_to_ohlcv_dataframe_empty_bars_returns_empty_frame_with_schema() -> None:
    df = to_ohlcv_dataframe([])
    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert df.index.name == "timestamp_utc"
    assert len(df) == 0


def test_to_ohlcv_dataframe_deduplicates_on_timestamp() -> None:
    ts = datetime(2025, 1, 1, 9, 30, tzinfo=UTC)
    bars = [_bar(ts, 100.0), _bar(ts, 105.0)]
    df = to_ohlcv_dataframe(bars)
    assert len(df) == 1
    assert df.loc[df.index[0], "close"] == 105.0
