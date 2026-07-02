from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from trade_vectorbt import (
    VectorbtSummary,
    build_vectorbt_summary,
    ma_cross_signals,
    run_vectorbt_backtest,
)

# ---------------------------------------------------------------------------
# build_vectorbt_summary: normal case (MA cross with trades)
# ---------------------------------------------------------------------------


def test_build_summary_returns_vectorbt_summary(synthetic_ohlcv: pd.DataFrame) -> None:
    close = synthetic_ohlcv["close"]
    sig = ma_cross_signals(close, fast=10, slow=30)
    result = run_vectorbt_backtest(close, sig.entries, sig.exits, init_cash=10_000, freq="D")
    summary = build_vectorbt_summary(result, strategy_name="ma_cross")
    assert isinstance(summary, VectorbtSummary)
    assert summary.strategy_name == "ma_cross"
    assert summary.n_bars == 200
    assert summary.init_cash == 10_000
    assert summary.direction == "both"
    assert summary.freq == "D"


def test_build_summary_portfolio_metrics(synthetic_ohlcv: pd.DataFrame) -> None:
    close = synthetic_ohlcv["close"]
    sig = ma_cross_signals(close, fast=10, slow=30)
    result = run_vectorbt_backtest(
        close, sig.entries, sig.exits, init_cash=10_000, fees=0.001, slippage=0.001, freq="D"
    )
    summary = build_vectorbt_summary(result, strategy_name="ma_cross")

    # total_return is a fraction (can be negative); always present.
    assert summary.total_return is not None
    assert isinstance(summary.total_return, float)

    # final_value equals init_cash + total_return * init_cash (approximately).
    assert summary.final_value > 0
    assert isinstance(summary.final_value, float)

    # Sharpe/Sortino can be finite or None depending on the random walk; with
    # trades they should be finite floats.
    if summary.sharpe_ratio is not None:
        assert isinstance(summary.sharpe_ratio, float)
    if summary.sortino_ratio is not None:
        assert isinstance(summary.sortino_ratio, float)

    # CAGR is computed from calendar span; with 200 daily bars it should exist.
    assert summary.cagr is not None
    assert isinstance(summary.cagr, float)

    # Max drawdown is a negative fraction (or 0 if strategy never loses).
    if summary.max_drawdown is not None:
        assert summary.max_drawdown <= 0

    # Duration in bars; with 200 bars and an active drawdown, this is positive.
    assert isinstance(summary.max_drawdown_duration_bars, int)
    assert summary.max_drawdown_duration_bars >= 0


def test_build_summary_trade_stats(synthetic_ohlcv: pd.DataFrame) -> None:
    close = synthetic_ohlcv["close"]
    sig = ma_cross_signals(close, fast=10, slow=30)
    result = run_vectorbt_backtest(close, sig.entries, sig.exits, init_cash=10_000, freq="D")
    summary = build_vectorbt_summary(result, strategy_name="ma_cross")

    # The synthetic data produces at least one trade (confirmed in Phase 2 tests).
    assert summary.total_trades >= 1
    assert summary.long_trades + summary.short_trades == summary.total_trades
    assert summary.winning_trades + summary.losing_trades <= summary.total_trades
    # Direction="both" means all trades are long or short.
    assert summary.direction == "both"


def test_build_summary_with_tp_stop(synthetic_ohlcv: pd.DataFrame) -> None:
    close = synthetic_ohlcv["close"]
    sig = ma_cross_signals(close, fast=10, slow=30)
    result = run_vectorbt_backtest(
        close, sig.entries, sig.exits, init_cash=10_000, tp_stop=0.05, freq="D"
    )
    summary = build_vectorbt_summary(result, strategy_name="ma_cross_tp")
    assert summary.tp_stop == 0.05
    assert summary.sl_trail is False


# ---------------------------------------------------------------------------
# build_vectorbt_summary: no-trade edge case
# ---------------------------------------------------------------------------


def test_build_summary_no_trades(synthetic_ohlcv: pd.DataFrame) -> None:
    """When entries/exits are all False, metrics should degrade gracefully to None."""
    close = synthetic_ohlcv["close"]
    no_entries = pd.Series(False, index=close.index)
    no_exits = pd.Series(False, index=close.index)
    result = run_vectorbt_backtest(close, no_entries, no_exits, init_cash=10_000, freq="D")
    summary = build_vectorbt_summary(result, strategy_name="noop")

    assert summary.total_trades == 0
    assert summary.long_trades == 0
    assert summary.short_trades == 0
    assert summary.winning_trades == 0
    assert summary.losing_trades == 0
    # total_return is 0.0 (no trades, no costs) — a valid float, not None.
    assert summary.total_return == 0.0
    assert summary.final_value == 10_000
    # Sharpe/Sortino are Inf with no trades → converted to None.
    assert summary.sharpe_ratio is None
    assert summary.sortino_ratio is None
    # Calmar is NaN → None.
    assert summary.calmar_ratio is None
    # Trade-level stats are NaN → None.
    assert summary.win_rate is None
    assert summary.profit_factor is None
    assert summary.expectancy is None
    assert summary.best_trade_return is None
    assert summary.worst_trade_return is None


# ---------------------------------------------------------------------------
# to_json_dict
# ---------------------------------------------------------------------------


def test_to_json_dict_produces_valid_json(synthetic_ohlcv: pd.DataFrame) -> None:
    close = synthetic_ohlcv["close"]
    sig = ma_cross_signals(close, fast=10, slow=30)
    result = run_vectorbt_backtest(close, sig.entries, sig.exits, init_cash=10_000, freq="D")
    summary = build_vectorbt_summary(result, strategy_name="ma_cross")
    d = summary.to_json_dict()

    # The dict must be json-serializable.
    json_str = json.dumps(d, indent=2, sort_keys=True)
    assert isinstance(json_str, str)

    # Round-trip: parse back and check key fields.
    parsed = json.loads(json_str)
    assert parsed["strategy_name"] == "ma_cross"
    assert parsed["n_bars"] == 200
    assert parsed["direction"] == "both"
    assert "init_cash" in parsed
    assert "final_value" in parsed

    # output_path must NOT be in the JSON payload.
    assert "output_path" not in parsed

    # Floats are stringified (mirrors str(Decimal) pattern in BacktestSummary).
    assert isinstance(parsed["init_cash"], str)
    assert isinstance(parsed["final_value"], str)


def test_to_json_dict_null_for_none_metrics(synthetic_ohlcv: pd.DataFrame) -> None:
    """NaN/Inf metrics serialize as JSON null, not 'NaN' or 'Infinity'."""
    close = synthetic_ohlcv["close"]
    no_entries = pd.Series(False, index=close.index)
    no_exits = pd.Series(False, index=close.index)
    result = run_vectorbt_backtest(close, no_entries, no_exits, init_cash=10_000, freq="D")
    summary = build_vectorbt_summary(result, strategy_name="noop")
    d = summary.to_json_dict()
    json_str = json.dumps(d)
    parsed = json.loads(json_str)

    # These should be null in the JSON, not 'NaN' or 'Infinity'.
    assert parsed["sharpe_ratio"] is None
    assert parsed["sortino_ratio"] is None
    assert parsed["calmar_ratio"] is None
    assert parsed["win_rate"] is None
    assert parsed["profit_factor"] is None


# ---------------------------------------------------------------------------
# Artifact writing
# ---------------------------------------------------------------------------


def test_build_summary_writes_artifact(synthetic_ohlcv: pd.DataFrame, tmp_path: Path) -> None:
    close = synthetic_ohlcv["close"]
    sig = ma_cross_signals(close, fast=10, slow=30)
    result = run_vectorbt_backtest(close, sig.entries, sig.exits, init_cash=10_000, freq="D")
    output = tmp_path / "backtests" / "vbt" / "ma_cross" / "summary.json"
    summary = build_vectorbt_summary(result, strategy_name="ma_cross", output_path=output)

    assert summary.output_path == output
    assert output.exists()
    # Artifact is valid JSON with the expected structure.
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert artifact["strategy_name"] == "ma_cross"
    assert artifact["n_bars"] == 200
    # output_path is excluded from the artifact payload.
    assert "output_path" not in artifact


def test_build_summary_no_output_path_does_not_write(
    synthetic_ohlcv: pd.DataFrame, tmp_path: Path
) -> None:
    close = synthetic_ohlcv["close"]
    sig = ma_cross_signals(close, fast=10, slow=30)
    result = run_vectorbt_backtest(close, sig.entries, sig.exits, init_cash=10_000, freq="D")
    summary = build_vectorbt_summary(result, strategy_name="ma_cross", output_path=None)

    assert summary.output_path is None
    # No files should have been created in tmp_path.
    assert list(tmp_path.iterdir()) == []
