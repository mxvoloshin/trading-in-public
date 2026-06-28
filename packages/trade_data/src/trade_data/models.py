"""Provider-neutral market data models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


def ensure_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime."""
    if value.tzinfo is None:
        msg = "datetime values must include timezone information"
        raise ValueError(msg)
    return value.astimezone(UTC)


def utc_to_json(value: datetime) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


def utc_from_json(value: str) -> datetime:
    return ensure_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


@dataclass(frozen=True, slots=True)
class Instrument:
    """Minimal v1 instrument mapping between project and provider identifiers."""

    instrument_id: str
    provider_symbol: str
    market: str
    currency: str = "USD"

    @classmethod
    def us_equity(cls, symbol: str, market: str = "XNYS") -> Instrument:
        normalized_symbol = symbol.strip().upper()
        return cls(
            instrument_id=f"{normalized_symbol}.US",
            provider_symbol=normalized_symbol,
            market=market,
            currency="USD",
        )


@dataclass(frozen=True, slots=True)
class HistoricalBarsRequest:
    """Provider-neutral historical bars request."""

    instrument: Instrument
    timeframe: str
    start_utc: datetime
    end_utc: datetime
    market: str = "XNYS"
    session: str = "regular"

    def __post_init__(self) -> None:
        start_utc = ensure_utc(self.start_utc)
        end_utc = ensure_utc(self.end_utc)
        if start_utc >= end_utc:
            msg = "start_utc must be before end_utc"
            raise ValueError(msg)
        object.__setattr__(self, "start_utc", start_utc)
        object.__setattr__(self, "end_utc", end_utc)


@dataclass(frozen=True, slots=True)
class Bar:
    """Strategy-facing OHLCV bar."""

    instrument_id: str
    timeframe: str
    timestamp_utc: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
    session: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp_utc", ensure_utc(self.timestamp_utc))

    def to_json_dict(self) -> dict[str, str | float | int]:
        return {
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "timestamp_utc": utc_to_json(self.timestamp_utc),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "session": self.session,
        }

    @classmethod
    def from_json_dict(cls, value: dict[str, Any]) -> Bar:
        return cls(
            instrument_id=str(value["instrument_id"]),
            timeframe=str(value["timeframe"]),
            timestamp_utc=utc_from_json(str(value["timestamp_utc"])),
            open=float(value["open"]),
            high=float(value["high"]),
            low=float(value["low"]),
            close=float(value["close"]),
            volume=int(value["volume"]),
            session=str(value["session"]),
        )


@dataclass(frozen=True, slots=True)
class HistoricalBarsResult:
    bars: tuple[Bar, ...]
    raw_pages_saved: int
    normalized_files_written: int
    filtered_bars: int
    source: str = "alpaca"


class HistoricalBarsSource(Protocol):
    """Provider-neutral historical bars source interface."""

    def get_historical_bars(self, request: HistoricalBarsRequest) -> HistoricalBarsResult: ...
