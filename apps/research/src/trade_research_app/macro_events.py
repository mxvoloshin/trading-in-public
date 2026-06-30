"""Public-safe scheduled macro event tags for research reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class MacroEvent:
    """One scheduled macro event date used for backtest diagnostics.

    Parameters:
        event_date: Market-local session date.
        label: Stable machine-friendly event label for report grouping.
        description: Human-readable description used in docs and review.
        source_url: Public source used when this fixture was last maintained.
    """

    event_date: date
    label: str
    description: str
    source_url: str


@dataclass(frozen=True, slots=True)
class MacroEventCalendar:
    """Manually maintained event-day lookup for research diagnostics."""

    events: tuple[MacroEvent, ...]

    def labels_for_date(self, event_date: date) -> tuple[str, ...]:
        """Return sorted event labels for a market-local session date."""
        return tuple(sorted(event.label for event in self.events if event.event_date == event_date))


BLS_2025_CALENDAR_URL = "https://www.bls.gov/schedule/2025/home.htm"
BLS_2026_CALENDAR_URL = "https://www.bls.gov/schedule/2026/home.htm"
FOMC_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def default_macro_event_calendar() -> MacroEventCalendar:
    """Return the first public fixture for high-impact scheduled macro sessions.

    The fixture intentionally starts with CPI, PPI, Employment Situation, and
    FOMC statement days because those were called out by the SPY VWAP research
    review. It is a reporting input, not a strategy filter.
    """
    events = (
        *_bls_events(
            "2025-07-03",
            "employment_situation",
            "Employment Situation for June 2025",
            BLS_2025_CALENDAR_URL,
        ),
        *_bls_events(
            "2025-07-15", "cpi", "Consumer Price Index for June 2025", BLS_2025_CALENDAR_URL
        ),
        *_bls_events(
            "2025-07-16", "ppi", "Producer Price Index for June 2025", BLS_2025_CALENDAR_URL
        ),
        *_fomc_events("2025-07-30"),
        *_bls_events(
            "2025-08-01",
            "employment_situation",
            "Employment Situation for July 2025",
            BLS_2025_CALENDAR_URL,
        ),
        *_bls_events(
            "2025-08-12", "cpi", "Consumer Price Index for July 2025", BLS_2025_CALENDAR_URL
        ),
        *_bls_events(
            "2025-08-14", "ppi", "Producer Price Index for July 2025", BLS_2025_CALENDAR_URL
        ),
        *_bls_events(
            "2025-09-05",
            "employment_situation",
            "Employment Situation for August 2025",
            BLS_2025_CALENDAR_URL,
        ),
        *_bls_events(
            "2025-09-10", "ppi", "Producer Price Index for August 2025", BLS_2025_CALENDAR_URL
        ),
        *_bls_events(
            "2025-09-11", "cpi", "Consumer Price Index for August 2025", BLS_2025_CALENDAR_URL
        ),
        *_fomc_events("2025-09-17"),
        *_bls_events(
            "2025-10-24", "cpi", "Consumer Price Index for September 2025", BLS_2025_CALENDAR_URL
        ),
        *_fomc_events("2025-10-29"),
        *_bls_events(
            "2025-11-20",
            "employment_situation",
            "Employment Situation for September 2025",
            BLS_2025_CALENDAR_URL,
        ),
        *_bls_events(
            "2025-11-25", "ppi", "Producer Price Index for September 2025", BLS_2025_CALENDAR_URL
        ),
        *_fomc_events("2025-12-10"),
        *_bls_events(
            "2025-12-16",
            "employment_situation",
            "Employment Situation for November 2025",
            BLS_2025_CALENDAR_URL,
        ),
        *_bls_events(
            "2025-12-18", "cpi", "Consumer Price Index for November 2025", BLS_2025_CALENDAR_URL
        ),
        *_bls_events(
            "2026-01-09",
            "employment_situation",
            "Employment Situation for December 2025",
            BLS_2026_CALENDAR_URL,
        ),
        *_bls_events(
            "2026-01-13", "cpi", "Consumer Price Index for December 2025", BLS_2026_CALENDAR_URL
        ),
        *_bls_events(
            "2026-01-14", "ppi", "Producer Price Index for November 2025", BLS_2026_CALENDAR_URL
        ),
        *_fomc_events("2026-01-28"),
        *_bls_events(
            "2026-01-30", "ppi", "Producer Price Index for December 2025", BLS_2026_CALENDAR_URL
        ),
        *_bls_events(
            "2026-02-11",
            "employment_situation",
            "Employment Situation for January 2026",
            BLS_2026_CALENDAR_URL,
        ),
        *_bls_events(
            "2026-02-13", "cpi", "Consumer Price Index for January 2026", BLS_2026_CALENDAR_URL
        ),
        *_bls_events(
            "2026-02-27", "ppi", "Producer Price Index for January 2026", BLS_2026_CALENDAR_URL
        ),
        *_bls_events(
            "2026-03-06",
            "employment_situation",
            "Employment Situation for February 2026",
            BLS_2026_CALENDAR_URL,
        ),
        *_bls_events(
            "2026-03-11", "cpi", "Consumer Price Index for February 2026", BLS_2026_CALENDAR_URL
        ),
        *_bls_events(
            "2026-03-18", "ppi", "Producer Price Index for February 2026", BLS_2026_CALENDAR_URL
        ),
        *_fomc_events("2026-03-18"),
        *_bls_events(
            "2026-04-03",
            "employment_situation",
            "Employment Situation for March 2026",
            BLS_2026_CALENDAR_URL,
        ),
        *_bls_events(
            "2026-04-10", "cpi", "Consumer Price Index for March 2026", BLS_2026_CALENDAR_URL
        ),
        *_bls_events(
            "2026-04-14", "ppi", "Producer Price Index for March 2026", BLS_2026_CALENDAR_URL
        ),
        *_fomc_events("2026-04-29"),
        *_bls_events(
            "2026-05-08",
            "employment_situation",
            "Employment Situation for April 2026",
            BLS_2026_CALENDAR_URL,
        ),
        *_bls_events(
            "2026-05-12", "cpi", "Consumer Price Index for April 2026", BLS_2026_CALENDAR_URL
        ),
        *_bls_events(
            "2026-05-13", "ppi", "Producer Price Index for April 2026", BLS_2026_CALENDAR_URL
        ),
        *_bls_events(
            "2026-06-05",
            "employment_situation",
            "Employment Situation for May 2026",
            BLS_2026_CALENDAR_URL,
        ),
        *_bls_events(
            "2026-06-10", "cpi", "Consumer Price Index for May 2026", BLS_2026_CALENDAR_URL
        ),
        *_bls_events(
            "2026-06-11", "ppi", "Producer Price Index for May 2026", BLS_2026_CALENDAR_URL
        ),
        *_fomc_events("2026-06-17"),
    )
    return MacroEventCalendar(events=events)


def _bls_events(
    event_date: str,
    label: str,
    description: str,
    source_url: str,
) -> tuple[MacroEvent, ...]:
    return (
        MacroEvent(
            event_date=date.fromisoformat(event_date),
            label=label,
            description=description,
            source_url=source_url,
        ),
    )


def _fomc_events(event_date: str) -> tuple[MacroEvent, ...]:
    return (
        MacroEvent(
            event_date=date.fromisoformat(event_date),
            label="fomc_statement",
            description="FOMC statement and press conference day",
            source_url=FOMC_CALENDAR_URL,
        ),
    )
