"""Lightweight market session classification."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from trade_data.models import ensure_utc


def _empty_holidays() -> frozenset[date]:
    return frozenset()


@dataclass(frozen=True, slots=True)
class MarketSessionConfig:
    """Small market calendar used for v1 session filtering.

    This intentionally models only what the first backtesting data path needs:
    timezone, regular hours, weekdays, and optional holidays. Full exchange
    calendars and early closes can come later when a strategy proves it needs them.
    """

    calendar_id: str
    timezone: str
    regular_open: time
    regular_close: time
    weekdays: frozenset[int] = frozenset({0, 1, 2, 3, 4})
    holidays: frozenset[date] = field(default_factory=_empty_holidays)

    @classmethod
    def xnys_regular(cls, holidays: frozenset[date] | None = None) -> MarketSessionConfig:
        return cls(
            calendar_id="XNYS",
            timezone="America/New_York",
            regular_open=time(hour=9, minute=30),
            regular_close=time(hour=16),
            holidays=holidays or frozenset(),
        )

    @property
    def zoneinfo(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def local_date_for(self, timestamp_utc: datetime) -> date:
        return ensure_utc(timestamp_utc).astimezone(self.zoneinfo).date()

    def classify(self, timestamp_utc: datetime) -> str:
        """Classify one UTC bar timestamp from the market's local perspective."""
        local_timestamp = ensure_utc(timestamp_utc).astimezone(self.zoneinfo)
        local_date = local_timestamp.date()
        local_time = local_timestamp.time()

        if local_timestamp.weekday() not in self.weekdays:
            return "closed"
        if local_date in self.holidays:
            return "closed"
        if self.regular_open <= local_time < self.regular_close:
            return "regular"
        return "extended"

    def is_selected(self, timestamp_utc: datetime, session: str) -> bool:
        if session == "all":
            return self.classify(timestamp_utc) != "closed"
        return self.classify(timestamp_utc) == session


DEFAULT_MARKET_SESSIONS: dict[str, MarketSessionConfig] = {
    "XNYS": MarketSessionConfig.xnys_regular(),
}


def get_market_session_config(calendar_id: str) -> MarketSessionConfig:
    try:
        return DEFAULT_MARKET_SESSIONS[calendar_id]
    except KeyError as error:
        msg = f"unsupported market calendar: {calendar_id}"
        raise ValueError(msg) from error
