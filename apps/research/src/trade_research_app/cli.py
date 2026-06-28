"""Command line tools for research workflows."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from trade_data import AlpacaHistoricalBarsSource, HistoricalBarsRequest, Instrument
from trade_data.sessions import get_market_session_config
from trade_data.store import LocalMarketDataStore


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return int(handler(args))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="trade_research_app")
    subcommands = parser.add_subparsers(dest="command")

    market_data = subcommands.add_parser("market-data")
    market_data_subcommands = market_data.add_subparsers(dest="market_data_command")

    fetch = market_data_subcommands.add_parser("fetch")
    fetch.add_argument("--symbol", required=True)
    fetch.add_argument("--timeframe", default="5Min")
    fetch.add_argument("--start", required=True, help="inclusive market-local date, YYYY-MM-DD")
    fetch.add_argument("--end", required=True, help="inclusive market-local date, YYYY-MM-DD")
    fetch.add_argument("--market", default="XNYS")
    fetch.add_argument("--session", default="regular", choices=["regular", "extended", "all"])
    fetch.add_argument("--cache-dir", default=".data")
    fetch.set_defaults(handler=_handle_market_data_fetch)

    return parser


def _handle_market_data_fetch(args: argparse.Namespace) -> int:
    session_config = get_market_session_config(str(args.market))
    start_date = date.fromisoformat(str(args.start))
    end_date = date.fromisoformat(str(args.end))
    if start_date > end_date:
        msg = "--start must be on or before --end"
        raise ValueError(msg)

    # Humans think in market-local dates ("fetch June 26"). Alpaca expects UTC
    # timestamps, so the CLI owns that conversion before constructing the request.
    start_utc, end_utc = inclusive_local_dates_to_utc_range(
        start_date=start_date,
        end_date=end_date,
        timezone=session_config.timezone,
    )
    instrument = Instrument.us_equity(symbol=str(args.symbol), market=str(args.market))
    request = HistoricalBarsRequest(
        instrument=instrument,
        timeframe=str(args.timeframe),
        start_utc=start_utc,
        end_utc=end_utc,
        market=str(args.market),
        session=str(args.session),
    )

    store = LocalMarketDataStore(Path(str(args.cache_dir)))
    source = AlpacaHistoricalBarsSource.from_env(store=store)
    result = source.get_historical_bars(request, session_config=session_config)

    print(f"source={result.source}")
    print(f"raw_pages_saved={result.raw_pages_saved}")
    print(f"bars_written={len(result.bars)}")
    print(f"normalized_files_written={result.normalized_files_written}")
    print(f"filtered_bars={result.filtered_bars}")
    return 0


def inclusive_local_dates_to_utc_range(
    *,
    start_date: date,
    end_date: date,
    timezone: str,
) -> tuple[datetime, datetime]:
    """Convert inclusive market-local dates to a UTC half-open range."""
    zone = ZoneInfo(timezone)
    start_local = datetime.combine(start_date, time.min, tzinfo=zone)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
