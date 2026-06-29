from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from pytest import CaptureFixture
from trade_data import Bar, HistoricalBarsRequest, Instrument, LocalMarketDataStore
from trade_data.sessions import MarketSessionConfig
from trade_research_app.backtest import BacktestCostModel, run_minimal_backtest
from trade_research_app.cli import main
from trade_strategies import get_strategy


def test_minimal_backtest_loads_cached_bars_and_writes_summary(tmp_path: Path) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)
    output_path = tmp_path / "backtests" / "summary.json"

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=output_path,
        strategy=get_strategy("close-momentum"),
        quantity=Decimal("1"),
    )

    assert summary.bars_loaded == 5
    assert summary.decisions == 5
    assert summary.approved_orders == 2
    assert summary.fills == 2
    assert summary.pending_orders == 0
    assert summary.ending_position == Decimal("0")
    assert summary.realized_pnl == Decimal("-1.0")
    assert summary.unrealized_pnl == Decimal("0")
    assert summary.total_pnl == Decimal("-1.0")
    expected_trade_bucket = {
        "average_holding_minutes": "10",
        "average_post_exit_max_favorable_pnl": "0.0",
        "closed_trades": 1,
        "expectancy": "-1.0",
        "losing_trades": 1,
        "max_post_exit_max_favorable_pnl": "0.0",
        "median_holding_minutes": "10",
        "median_post_exit_max_favorable_pnl": "0.0",
        "total_pnl": "-1.0",
        "win_rate": "0",
        "winning_trades": 0,
    }
    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "approved_orders": 2,
        "average_holding_minutes": "10",
        "average_loss": "-1.0",
        "average_post_exit_max_favorable_pnl": "0.0",
        "average_win": "0",
        "bars_loaded": 5,
        "best_trade_pnl": "-1.0",
        "closed_trades": 1,
        "cost_per_closed_trade": "0.0",
        "daily_breakdown": {"2026-06-26": expected_trade_bucket},
        "decisions": 5,
        "ending_position": "0",
        "exit_reason_breakdown": {"close_below_previous_close": expected_trade_bucket},
        "expectancy_per_day": "-1.0",
        "expectancy_per_trade": "-1.0",
        "fills": 2,
        "holding_time_breakdown": {"00-30m": expected_trade_bucket},
        "instrument_id": "SPY.US",
        "longest_holding_minutes": 10,
        "losing_trades": 1,
        "max_drawdown": "-1.0",
        "max_drawdown_duration_trades": 1,
        "max_post_exit_max_favorable_pnl": "0.0",
        "median_holding_minutes": "10",
        "median_post_exit_max_favorable_pnl": "0.0",
        "median_trade_pnl": "-1.0",
        "minimum_commission": "0",
        "pending_orders": 0,
        "profit_factor": "0",
        "realized_pnl": "-1.0",
        "commission_per_share": "0",
        "slippage_bps": "0",
        "strategy_name": "close-momentum",
        "timeframe": "5Min",
        "total_commissions": "0",
        "total_execution_costs": "0.0",
        "total_slippage_cost": "0.0",
        "total_pnl": "-1.0",
        "time_of_day_breakdown": {"09:30-10:00": expected_trade_bucket},
        "unrealized_pnl": "0",
        "win_rate": "0",
        "winning_trades": 0,
        "worst_trade_pnl": "-1.0",
    }


def test_backtest_cli_runs_against_local_cache(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)
    output_path = tmp_path / "summary.json"

    exit_code = main(
        [
            "backtest",
            "run",
            "--symbol",
            "SPY",
            "--strategy",
            "close-momentum",
            "--timeframe",
            "5Min",
            "--start",
            "2026-06-26",
            "--end",
            "2026-06-26",
            "--cache-dir",
            str(tmp_path),
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "strategy=close-momentum" in output
    assert "bars_loaded=5" in output
    assert "pending_orders=0" in output
    assert "realized_pnl=-1.0" in output
    assert "total_pnl=-1.0" in output
    assert "slippage_bps=0" in output
    assert "total_commissions=0" in output
    assert "total_slippage_cost=0.0" in output
    assert "expectancy_per_trade=-1.0" in output
    assert "median_trade_pnl=-1.0" in output
    assert "closed_trades=1" in output
    assert "profit_factor=0" in output
    assert "average_holding_minutes=10" in output
    assert "median_holding_minutes=10" in output
    assert "longest_holding_minutes=10" in output
    assert "average_post_exit_max_favorable_pnl=0.0" in output
    assert "median_post_exit_max_favorable_pnl=0.0" in output
    assert "max_post_exit_max_favorable_pnl=0.0" in output


def test_minimal_backtest_applies_commission_costs(tmp_path: Path) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=None,
        strategy=get_strategy("close-momentum"),
        quantity=Decimal("1"),
        cost_model=BacktestCostModel(commission_per_share=Decimal("0.10")),
    )

    assert summary.fills == 2
    assert summary.total_commissions == Decimal("0.20")
    assert summary.total_execution_costs == Decimal("0.20")
    assert summary.cost_per_closed_trade == Decimal("0.20")
    assert summary.realized_pnl == Decimal("-1.20")
    assert summary.total_pnl == Decimal("-1.20")
    assert summary.expectancy_per_trade == Decimal("-1.20")
    assert summary.average_loss == Decimal("-1.20")
    assert summary.max_drawdown == Decimal("-1.20")


def test_minimal_backtest_applies_one_way_slippage(tmp_path: Path) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=None,
        strategy=get_strategy("close-momentum"),
        quantity=Decimal("1"),
        cost_model=BacktestCostModel(slippage_bps=Decimal("100")),
    )

    assert summary.fills == 2
    assert summary.total_slippage_cost == Decimal("2.020")
    assert summary.total_execution_costs == Decimal("2.020")
    assert summary.realized_pnl == Decimal("-3.020")
    assert summary.total_pnl == Decimal("-3.020")


def test_minimal_backtest_reports_trade_breakdowns(tmp_path: Path) -> None:
    request = _request()
    _save_sample_bars(tmp_path, request)

    summary = run_minimal_backtest(
        request=request,
        cache_dir=tmp_path,
        output_path=None,
        strategy=get_strategy("close-momentum"),
        quantity=Decimal("1"),
    )

    assert summary.expectancy_per_day == Decimal("-1.0")
    assert summary.best_trade_pnl == Decimal("-1.0")
    assert summary.worst_trade_pnl == Decimal("-1.0")
    assert summary.max_drawdown_duration_trades == 1
    assert summary.average_holding_minutes == Decimal("10")
    assert summary.median_holding_minutes == Decimal("10")
    assert summary.longest_holding_minutes == 10
    assert summary.average_post_exit_max_favorable_pnl == Decimal("0.0")
    assert summary.median_post_exit_max_favorable_pnl == Decimal("0.0")
    assert summary.max_post_exit_max_favorable_pnl == Decimal("0.0")
    expected_trade_bucket = {
        "average_holding_minutes": "10",
        "average_post_exit_max_favorable_pnl": "0.0",
        "closed_trades": 1,
        "expectancy": "-1.0",
        "losing_trades": 1,
        "max_post_exit_max_favorable_pnl": "0.0",
        "median_holding_minutes": "10",
        "median_post_exit_max_favorable_pnl": "0.0",
        "total_pnl": "-1.0",
        "win_rate": "0",
        "winning_trades": 0,
    }
    assert summary.daily_breakdown == {"2026-06-26": expected_trade_bucket}
    assert summary.time_of_day_breakdown == {"09:30-10:00": expected_trade_bucket}
    assert summary.exit_reason_breakdown == {"close_below_previous_close": expected_trade_bucket}
    assert summary.holding_time_breakdown == {"00-30m": expected_trade_bucket}


def _request() -> HistoricalBarsRequest:
    return HistoricalBarsRequest(
        instrument=Instrument.us_equity("SPY"),
        timeframe="5Min",
        start_utc=datetime(2026, 6, 26, 4, 0, tzinfo=UTC),
        end_utc=datetime(2026, 6, 27, 4, 0, tzinfo=UTC),
    )


def _save_sample_bars(cache_dir: Path, request: HistoricalBarsRequest) -> None:
    bars = (
        _bar(open=100.0, close=100.0, minute=30),
        _bar(open=100.0, close=101.0, minute=35),
        _bar(open=101.5, close=102.0, minute=40),
        _bar(open=102.0, close=101.0, minute=45),
        _bar(open=100.5, close=100.0, minute=50),
    )
    session_config = MarketSessionConfig.xnys_regular()
    regular_bars = tuple(
        bar for bar in bars if session_config.classify(bar.timestamp_utc) == "regular"
    )
    LocalMarketDataStore(cache_dir).save_normalized_bars(regular_bars, request, session_config)


def _bar(*, open: float, close: float, minute: int) -> Bar:
    return Bar(
        instrument_id="SPY.US",
        timeframe="5Min",
        timestamp_utc=datetime(2026, 6, 26, 13, minute, tzinfo=UTC),
        open=open,
        high=max(open, close),
        low=min(open, close),
        close=close,
        volume=1_000,
        session="regular",
    )
