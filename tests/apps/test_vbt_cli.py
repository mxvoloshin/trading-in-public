"""Tests for the ``backtest vbt`` CLI subcommand.

These tests exercise the full CLI path: parser → handler → vbt runner →
artifact write. They create sample 5Min bars in a local cache (enough for
MA/RSI/ATR indicator warmup and crossover events), invoke ``main()`` with
the vbt subcommand args, and assert the printed output and JSON artifact.

The tests don't import pandas/vectorbt directly — they go through the CLI
which returns a well-typed ``VectorbtSummary`` — so strict pyright is
preserved in this test file.
"""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pytest import CaptureFixture
from trade_data import Bar, HistoricalBarsRequest, Instrument, LocalMarketDataStore
from trade_data.sessions import MarketSessionConfig
from trade_research_app.cli import main


def test_vbt_cli_ma_cross_runs_and_prints_metrics(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """MA crossover: CLI produces metrics and writes a JSON artifact."""
    request = _request()
    _save_trending_bars(tmp_path, request)
    output_path = tmp_path / "vbt_summary.json"

    exit_code = main(
        [
            "backtest",
            "vbt",
            "--strategy",
            "ma-cross",
            "--symbol",
            "SPY",
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-05",
            "--cache-dir",
            str(tmp_path),
            "--output",
            str(output_path),
            "--fast",
            "10",
            "--slow",
            "30",
            "--direction",
            "longonly",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "strategy=ma-cross" in output
    assert "total_return=" in output
    assert "sharpe_ratio=" in output
    assert "total_trades=" in output
    assert "n_bars=" in output
    assert f"output={output_path}" in output

    # Artifact file should exist and contain expected keys.
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["strategy_name"] == "ma-cross"
    assert "total_return" in artifact
    assert "sharpe_ratio" in artifact
    assert "max_drawdown" in artifact
    assert "total_trades" in artifact
    assert "n_bars" in artifact
    assert artifact["n_bars"] == 390  # 5 days * 78 bars/day


def test_vbt_cli_rsi_revert_runs_and_writes_artifact(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """RSI mean-reversion: CLI runs and writes artifact with strategy label."""
    request = _request()
    _save_trending_bars(tmp_path, request)
    output_path = tmp_path / "rsi_summary.json"

    exit_code = main(
        [
            "backtest",
            "vbt",
            "--strategy",
            "rsi-revert",
            "--symbol",
            "SPY",
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-05",
            "--cache-dir",
            str(tmp_path),
            "--output",
            str(output_path),
            "--window",
            "14",
            "--lower",
            "30",
            "--upper",
            "70",
            "--direction",
            "longonly",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "strategy=rsi-revert" in output
    assert "total_return=" in output

    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["strategy_name"] == "rsi-revert"
    assert artifact["direction"] == "longonly"


def test_vbt_cli_atr_trail_runs_and_writes_artifact(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """ATR trailing stop: CLI runs and artifact records sl_trail=True."""
    request = _request()
    _save_trending_bars(tmp_path, request)
    output_path = tmp_path / "atr_summary.json"

    exit_code = main(
        [
            "backtest",
            "vbt",
            "--strategy",
            "atr-trail",
            "--symbol",
            "SPY",
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-05",
            "--cache-dir",
            str(tmp_path),
            "--output",
            str(output_path),
            "--window",
            "14",
            "--multiplier",
            "2",
            "--direction",
            "longonly",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "strategy=atr-trail" in output
    assert "sl_trail=True" in output

    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["strategy_name"] == "atr-trail"
    assert artifact["sl_trail"] is True
    assert artifact["sl_stop"] == "per_bar"


def test_vbt_cli_default_output_path_used_when_no_output_flag(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """When --output is omitted, the default path under .data/backtests/vbt/ is used."""
    request = _request()
    _save_trending_bars(tmp_path, request)

    exit_code = main(
        [
            "backtest",
            "vbt",
            "--strategy",
            "ma-cross",
            "--symbol",
            "SPY",
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-05",
            "--cache-dir",
            str(tmp_path),
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    # The default output path should be printed and the file should exist.
    assert "output=" in output
    output_line = [line for line in output.splitlines() if line.startswith("output=")]
    assert len(output_line) == 1
    default_path = Path(output_line[0].removeprefix("output="))
    assert default_path.exists()
    assert "backtests" in str(default_path)
    assert "vbt" in str(default_path)
    assert "ma-cross" in str(default_path)


def test_vbt_cli_with_fees_and_slippage(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Fees and slippage are passed through and appear in output and artifact."""
    request = _request()
    _save_trending_bars(tmp_path, request)
    output_path = tmp_path / "summary.json"

    exit_code = main(
        [
            "backtest",
            "vbt",
            "--strategy",
            "ma-cross",
            "--symbol",
            "SPY",
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-05",
            "--cache-dir",
            str(tmp_path),
            "--output",
            str(output_path),
            "--fees",
            "0.001",
            "--slippage",
            "0.0005",
            "--init-cash",
            "50000",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "fees=0.001" in output
    assert "slippage=0.0005" in output
    assert "init_cash=50000.0" in output

    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["fees"] == "0.001"
    assert artifact["slippage"] == "0.0005"


def test_vbt_cli_sl_stop_and_tp_stop(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Stop-loss and take-profit fractions are passed through."""
    request = _request()
    _save_trending_bars(tmp_path, request)
    output_path = tmp_path / "summary.json"

    exit_code = main(
        [
            "backtest",
            "vbt",
            "--strategy",
            "ma-cross",
            "--symbol",
            "SPY",
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-05",
            "--cache-dir",
            str(tmp_path),
            "--output",
            str(output_path),
            "--sl-stop",
            "0.03",
            "--tp-stop",
            "0.05",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "sl_stop=0.03" in output
    assert "tp_stop=0.05" in output
    assert "sl_trail=False" in output


def test_vbt_cli_invalid_strategy_returns_error(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """An invalid strategy name should not be accepted by the parser."""
    request = _request()
    _save_trending_bars(tmp_path, request)

    # argparse rejects invalid choices by calling sys.exit(2), which raises
    # SystemExit. We catch it and verify the exit code.
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "backtest",
                "vbt",
                "--strategy",
                "nonexistent",
                "--symbol",
                "SPY",
                "--start",
                "2026-06-01",
                "--end",
                "2026-06-05",
                "--cache-dir",
                str(tmp_path),
            ]
        )

    assert exc_info.value.code == 2


def test_vbt_cli_orb_strategy_runs_and_writes_artifact(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """ORB strategy: CLI runs, produces metrics, and writes a JSON artifact."""
    request = _request()
    _save_trending_bars(tmp_path, request)
    output_path = tmp_path / "orb_summary.json"

    exit_code = main(
        [
            "backtest",
            "vbt",
            "--strategy",
            "orb",
            "--symbol",
            "SPY",
            "--start",
            "2026-06-01",
            "--end",
            "2026-06-05",
            "--cache-dir",
            str(tmp_path),
            "--output",
            str(output_path),
            "--opening-range-bars",
            "6",
            "--direction",
            "longonly",
        ]
    )

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "strategy=orb" in output
    assert "total_return=" in output
    assert "sharpe_ratio=" in output
    assert "total_trades=" in output
    assert "n_bars=" in output
    assert f"output={output_path}" in output

    # Artifact file should exist and contain expected keys.
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["strategy_name"] == "orb"
    assert "total_return" in artifact
    assert "sharpe_ratio" in artifact
    assert "max_drawdown" in artifact
    assert "total_trades" in artifact
    assert "n_bars" in artifact


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _request() -> HistoricalBarsRequest:
    """Standard 5Min SPY request for June 1-5, 2026 (Mon-Fri week)."""
    return HistoricalBarsRequest(
        instrument=Instrument.us_equity("SPY"),
        timeframe="5Min",
        start_utc=datetime(2026, 6, 1, 4, 0, tzinfo=UTC),
        end_utc=datetime(2026, 6, 6, 4, 0, tzinfo=UTC),
    )


def _save_trending_bars(cache_dir: Path, request: HistoricalBarsRequest) -> None:
    """Create 5 days of 5Min bars with an oscillating uptrend.

    The sine-wave overlay on a gentle uptrend ensures MA(10) and MA(30)
    cross above and below each other multiple times, producing entry/exit
    signals. RSI dips below 30 and rises above 70 during the oscillations.
    ATR is non-trivial because the high-low range varies with the sine.
    """
    session_config = MarketSessionConfig.xnys_regular()
    bars: list[Bar] = []
    # bar_index counts across all days for the price pattern.
    bar_index = 0
    for day in range(1, 6):  # June 1-5, 2026 (Mon-Fri)
        for j in range(78):  # 78 5-min bars per regular session
            minute_offset = 30 + j * 5
            hour = 13 + minute_offset // 60
            minute = minute_offset % 60
            timestamp = datetime(2026, 6, day, hour, minute, tzinfo=UTC)

            # Sine-wave price around a gentle uptrend. Amplitude is large
            # enough to produce MA crossovers and RSI extremes.
            close = 100.0 + bar_index * 0.03 + 4.0 * math.sin(bar_index / 8)
            open_ = close - 0.2 * math.sin(bar_index / 5)
            high = max(open_, close) + 0.5 + 0.3 * abs(math.sin(bar_index / 3))
            low = min(open_, close) - 0.5 - 0.3 * abs(math.sin(bar_index / 3))
            volume = 1000 + int(200 * math.sin(bar_index / 10))

            bars.append(
                Bar(
                    instrument_id="SPY.US",
                    timeframe="5Min",
                    timestamp_utc=timestamp,
                    open=open_,
                    high=high,
                    low=low,
                    close=close,
                    volume=volume,
                    session="regular",
                )
            )
            bar_index += 1

    # Filter to regular session bars (the session_config excludes non-regular).
    regular_bars = tuple(
        bar for bar in bars if session_config.classify(bar.timestamp_utc) == "regular"
    )
    LocalMarketDataStore(cache_dir).save_normalized_bars(regular_bars, request, session_config)
