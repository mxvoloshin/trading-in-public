from __future__ import annotations

from datetime import UTC, date, datetime

from trade_research_app.cli import inclusive_local_dates_to_utc_range


def test_cli_date_range_uses_inclusive_market_local_dates() -> None:
    start_utc, end_utc = inclusive_local_dates_to_utc_range(
        start_date=date(2026, 6, 26),
        end_date=date(2026, 6, 26),
        timezone="America/New_York",
    )

    assert start_utc == datetime(2026, 6, 26, 4, 0, tzinfo=UTC)
    assert end_utc == datetime(2026, 6, 27, 4, 0, tzinfo=UTC)
