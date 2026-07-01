"""Command line tools for research workflows."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from trade_data import AlpacaHistoricalBarsSource, HistoricalBarsRequest, Instrument
from trade_data.sessions import get_market_session_config
from trade_data.store import LocalMarketDataStore
from trade_strategies import get_strategy, list_strategy_names

from trade_research_app.backtest import (
    BacktestCostModel,
    run_cost_stress_report,
    run_minimal_backtest,
)


def main(argv: list[str] | None = None) -> int:
    """Run the research command line interface.

    Parameters:
        argv: Optional argument list for tests. `None` uses process arguments.
    """
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 2
    return int(handler(args))


def _build_parser() -> argparse.ArgumentParser:
    """Create the research CLI parser with market-data and backtest commands."""
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

    backtest = subcommands.add_parser("backtest")
    backtest_subcommands = backtest.add_subparsers(dest="backtest_command")

    run = backtest_subcommands.add_parser("run")
    run.add_argument("--strategy", default="close-momentum", choices=list_strategy_names())
    run.add_argument("--symbol", required=True)
    run.add_argument("--timeframe", default="5Min")
    run.add_argument("--start", required=True, help="inclusive market-local date, YYYY-MM-DD")
    run.add_argument("--end", required=True, help="inclusive market-local date, YYYY-MM-DD")
    run.add_argument("--market", default="XNYS")
    run.add_argument("--session", default="regular", choices=["regular", "extended", "all"])
    run.add_argument("--cache-dir", default=".data")
    run.add_argument("--quantity", default="1")
    run.add_argument("--slippage-bps", default="0")
    run.add_argument("--commission-per-share", default="0")
    run.add_argument("--minimum-commission", default="0")
    run.add_argument("--output", default=None)
    run.set_defaults(handler=_handle_backtest_run)

    cost_stress = backtest_subcommands.add_parser("cost-stress")
    cost_stress.add_argument("--strategy", default="close-momentum", choices=list_strategy_names())
    cost_stress.add_argument("--symbol", required=True)
    cost_stress.add_argument("--timeframe", default="5Min")
    cost_stress.add_argument(
        "--start", required=True, help="inclusive market-local date, YYYY-MM-DD"
    )
    cost_stress.add_argument("--end", required=True, help="inclusive market-local date, YYYY-MM-DD")
    cost_stress.add_argument("--market", default="XNYS")
    cost_stress.add_argument("--session", default="regular", choices=["regular", "extended", "all"])
    cost_stress.add_argument("--cache-dir", default=".data")
    cost_stress.add_argument("--quantity", default="1")
    cost_stress.add_argument("--output", default=None)
    cost_stress.set_defaults(handler=_handle_backtest_cost_stress)

    return parser


def _handle_market_data_fetch(args: argparse.Namespace) -> int:
    """Fetch historical bars from Alpaca and write normalized local cache files."""
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


def _handle_backtest_run(args: argparse.Namespace) -> int:
    """Run a selected strategy against locally cached normalized bars."""
    request = _historical_bars_request_from_args(args)
    output_path = (
        Path(str(args.output))
        if args.output is not None
        else _default_backtest_output_path(
            cache_dir=Path(str(args.cache_dir)),
            request=request,
            strategy_name=str(args.strategy),
        )
    )
    summary = run_minimal_backtest(
        request=request,
        cache_dir=Path(str(args.cache_dir)),
        output_path=output_path,
        strategy=get_strategy(str(args.strategy)),
        quantity=Decimal(str(args.quantity)),
        cost_model=BacktestCostModel(
            slippage_bps=Decimal(str(args.slippage_bps)),
            commission_per_share=Decimal(str(args.commission_per_share)),
            minimum_commission=Decimal(str(args.minimum_commission)),
        ),
    )

    print(f"strategy_name={summary.strategy_name}")
    print(f"variant_name={summary.variant_name}")
    print(f"trades={summary.trades}")
    print(f"long_trades={summary.long_trades}")
    print(f"short_trades={summary.short_trades}")
    print(f"gross_pnl={summary.gross_pnl}")
    print(f"costed_pnl={summary.costed_pnl}")
    print(f"profit_factor={summary.profit_factor}")
    print(f"expectancy_per_trade={summary.expectancy_per_trade}")
    print(f"win_rate={summary.win_rate}")
    print(f"average_win={summary.average_win}")
    print(f"average_loss={summary.average_loss}")
    print(f"max_drawdown={summary.max_drawdown}")
    print(f"worst_rolling_3_month={summary.worst_rolling_3_month}")
    print(f"worst_rolling_6_month={summary.worst_rolling_6_month}")
    print(f"largest_trade_pct_of_total_pnl={summary.largest_trade_pct_of_total_pnl}")
    print(
        f"top_5_absolute_trades_pct_of_total_pnl={summary.top_5_absolute_trades_pct_of_total_pnl}"
    )
    print(f"long_pnl={summary.long_pnl}")
    print(f"short_pnl={summary.short_pnl}")
    print(f"long_pf={summary.long_pf}")
    print(f"short_pf={summary.short_pf}")
    print(f"long_expectancy={summary.long_expectancy}")
    print(f"short_expectancy={summary.short_expectancy}")
    print(f"strategy={summary.variant_name}")
    print(f"bars_loaded={summary.bars_loaded}")
    print(f"decisions={summary.decisions}")
    print(f"approved_orders={summary.approved_orders}")
    print(f"fills={summary.fills}")
    print(f"pending_orders={summary.pending_orders}")
    print(f"ending_position={summary.ending_position}")
    print(f"realized_pnl={summary.realized_pnl}")
    print(f"unrealized_pnl={summary.unrealized_pnl}")
    print(f"total_pnl={summary.total_pnl}")
    print(f"slippage_bps={summary.slippage_bps}")
    print(f"commission_per_share={summary.commission_per_share}")
    print(f"minimum_commission={summary.minimum_commission}")
    print(f"total_commissions={summary.total_commissions}")
    print(f"total_slippage_cost={summary.total_slippage_cost}")
    print(f"total_execution_costs={summary.total_execution_costs}")
    print(f"cost_per_closed_trade={summary.cost_per_closed_trade}")
    print(f"closed_trades={summary.closed_trades}")
    print(f"winning_trades={summary.winning_trades}")
    print(f"losing_trades={summary.losing_trades}")
    print(f"win_rate={summary.win_rate}")
    print(f"expectancy_per_trade={summary.expectancy_per_trade}")
    print(f"expectancy_per_day={summary.expectancy_per_day}")
    print(f"median_trade_pnl={summary.median_trade_pnl}")
    print(f"average_win={summary.average_win}")
    print(f"average_loss={summary.average_loss}")
    print(f"best_trade_pnl={summary.best_trade_pnl}")
    print(f"worst_trade_pnl={summary.worst_trade_pnl}")
    print(f"profit_factor={summary.profit_factor}")
    print(f"max_drawdown={summary.max_drawdown}")
    print(f"max_drawdown_duration_trades={summary.max_drawdown_duration_trades}")
    print(f"max_consecutive_losing_trades={summary.max_consecutive_losing_trades}")
    print(f"average_holding_minutes={summary.average_holding_minutes}")
    print(f"median_holding_minutes={summary.median_holding_minutes}")
    print(f"longest_holding_minutes={summary.longest_holding_minutes}")
    print(f"average_post_exit_max_favorable_pnl={summary.average_post_exit_max_favorable_pnl}")
    print(f"median_post_exit_max_favorable_pnl={summary.median_post_exit_max_favorable_pnl}")
    print(f"max_post_exit_max_favorable_pnl={summary.max_post_exit_max_favorable_pnl}")
    if summary.output_path is not None:
        print(f"output={summary.output_path}")
    return 0


def _handle_backtest_cost_stress(args: argparse.Namespace) -> int:
    """Run a selected strategy across the standard execution-cost grid."""
    request = _historical_bars_request_from_args(args)
    output_path = (
        Path(str(args.output))
        if args.output is not None
        else _default_cost_stress_output_path(
            cache_dir=Path(str(args.cache_dir)),
            request=request,
            strategy_name=str(args.strategy),
        )
    )
    report = run_cost_stress_report(
        request=request,
        cache_dir=Path(str(args.cache_dir)),
        output_path=output_path,
        strategy_factory=lambda: get_strategy(str(args.strategy)),
        quantity=Decimal(str(args.quantity)),
    )

    print(f"strategy={report.strategy_name}")
    print(f"instrument_id={report.instrument_id}")
    print(f"timeframe={report.timeframe}")
    for row in report.rows:
        print(
            "scenario="
            f"{row.scenario_name} "
            f"slippage_bps={row.slippage_bps} "
            f"commission_per_share={row.commission_per_share} "
            f"minimum_commission={row.minimum_commission} "
            f"total_pnl={row.total_pnl} "
            f"expectancy_per_trade={row.expectancy_per_trade} "
            f"profit_factor={row.profit_factor} "
            f"total_execution_costs={row.total_execution_costs} "
            f"cost_drag_from_gross={row.cost_drag_from_gross} "
            f"gross_edge_consumed={row.gross_edge_consumed} "
            f"median_post_exit_max_favorable_pnl={row.median_post_exit_max_favorable_pnl}"
        )
    if report.output_path is not None:
        print(f"output={report.output_path}")
    return 0


def _historical_bars_request_from_args(args: argparse.Namespace) -> HistoricalBarsRequest:
    """Convert CLI args into the provider-neutral historical bars request."""
    session_config = get_market_session_config(str(args.market))
    start_date = date.fromisoformat(str(args.start))
    end_date = date.fromisoformat(str(args.end))
    if start_date > end_date:
        msg = "--start must be on or before --end"
        raise ValueError(msg)

    start_utc, end_utc = inclusive_local_dates_to_utc_range(
        start_date=start_date,
        end_date=end_date,
        timezone=session_config.timezone,
    )
    return HistoricalBarsRequest(
        instrument=Instrument.us_equity(symbol=str(args.symbol), market=str(args.market)),
        timeframe=str(args.timeframe),
        start_utc=start_utc,
        end_utc=end_utc,
        market=str(args.market),
        session=str(args.session),
    )


def _default_backtest_output_path(
    *,
    cache_dir: Path,
    request: HistoricalBarsRequest,
    strategy_name: str,
) -> Path:
    """Return the default gitignored summary path for one strategy run."""
    start = request.start_utc.strftime("%Y%m%dT%H%M%SZ")
    end = request.end_utc.strftime("%Y%m%dT%H%M%SZ")
    filename = f"{request.instrument.instrument_id}_{request.timeframe}_{start}_{end}.json"
    return cache_dir / "backtests" / "minimal" / strategy_name / filename


def _default_cost_stress_output_path(
    *,
    cache_dir: Path,
    request: HistoricalBarsRequest,
    strategy_name: str,
) -> Path:
    """Return the default gitignored cost-stress report path."""
    start = request.start_utc.strftime("%Y%m%dT%H%M%SZ")
    end = request.end_utc.strftime("%Y%m%dT%H%M%SZ")
    filename = f"{request.instrument.instrument_id}_{request.timeframe}_{start}_{end}.json"
    return cache_dir / "backtests" / "cost-stress" / strategy_name / filename


def inclusive_local_dates_to_utc_range(
    *,
    start_date: date,
    end_date: date,
    timezone: str,
) -> tuple[datetime, datetime]:
    """Convert inclusive market-local dates to a UTC half-open range.

    Parameters:
        start_date: First market-local calendar date to include.
        end_date: Last market-local calendar date to include.
        timezone: IANA market timezone used to translate dates to UTC.
    """
    zone = ZoneInfo(timezone)
    start_local = datetime.combine(start_date, time.min, tzinfo=zone)
    end_local = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=zone)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)
