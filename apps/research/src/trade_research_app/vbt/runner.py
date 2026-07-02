"""VectorBT backtest runner for the ``backtest vbt`` CLI subcommand.

This module is the bridge between the CLI (argument parsing + output printing)
and the ``trade_vectorbt`` package (adapter, signals, runner, summary). It owns
the pandas/vectorbt interaction so that ``cli.py`` only handles well-typed
objects (``HistoricalBarsRequest``, ``VectorbtSummary``).

Pyright is relaxed for this sub-package because vectorbt/pandas ship without
type stubs; the scope is documented in the root ``pyproject.toml``
``executionEnvironments`` section.
"""

from __future__ import annotations

from pathlib import Path

from trade_data import HistoricalBarsRequest, LocalMarketDataStore
from trade_data.sessions import get_market_session_config
from trade_vectorbt import (
    VectorbtSummary,
    atr_trail_signals,
    build_vectorbt_summary,
    ma_cross_signals,
    orb_signals,
    rsi_revert_signals,
    run_vectorbt_backtest,
    to_ohlcv_dataframe,
)

# Map the repo's timeframe strings (used by the data layer) to pandas
# frequency aliases (used by vectorbt for annualized metric computation).
# Intraday data with session gaps breaks vectorbt's auto-inference, so we
# always pass an explicit freq to the runner.
_TIMEFRAME_TO_FREQ: dict[str, str] = {
    "1Min": "1min",
    "5Min": "5min",
    "15Min": "15min",
    "30Min": "30min",
    "1H": "1h",
    "1D": "D",
}

_VALID_STRATEGIES = ("ma-cross", "rsi-revert", "atr-trail", "orb")


def run_vbt_backtest(
    *,
    request: HistoricalBarsRequest,
    cache_dir: Path,
    strategy_name: str,
    output_path: Path | None = None,
    init_cash: float = 10_000.0,
    fees: float = 0.0,
    slippage: float = 0.0,
    direction: str = "longonly",
    freq: str | None = None,
    sl_stop: float | None = None,
    tp_stop: float | None = None,
    # Strategy-specific parameters (ignored by strategies that don't use them)
    fast: int = 10,
    slow: int = 30,
    window: int = 14,
    lower: float = 30.0,
    upper: float = 70.0,
    multiplier: float = 2.0,
    opening_range_bars: int = 6,
) -> VectorbtSummary:
    """Load bars, generate signals, run the vectorbt simulation, and build the summary.

    This is the vectorbt-track analog of the existing engine's
    ``run_minimal_backtest``: it takes a provider-neutral request, loads cached
    bars, runs the simulation, and writes the JSON artifact. The summary return
    type is well-typed (``VectorbtSummary``) so the CLI handler doesn't touch
    any pandas/vectorbt objects.

    Parameters:
        request: Provider-neutral bar request identifying instrument, timeframe,
            market, session, and date range.
        cache_dir: Root directory for the local normalized bar cache.
        strategy_name: One of ``"ma-cross"``, ``"rsi-revert"``, ``"atr-trail"``,
            ``"orb"``.
        output_path: Where to write the JSON summary. ``None`` skips writing.
        init_cash: Starting cash for the simulated account.
        fees: Transaction cost as a **fraction of trade value** (0.001 = 0.1%).
        slippage: One-way slippage as a fraction of price (0.001 = 0.1%).
        direction: ``"longonly"``, ``"shortonly"``, or ``"both"``.
        freq: Bar frequency for annualized metrics (e.g. ``"5min"``, ``"D"``).
            ``None`` infers from the request timeframe.
        sl_stop: Stop-loss as a fraction of price (0.03 = 3%). Ignored for
            ATR-trail which uses a per-bar Series.
        tp_stop: Take-profit as a fraction of price (0.05 = 5%).
        fast: Fast MA window for ``ma-cross``.
        slow: Slow MA window for ``ma-cross``.
        window: RSI/ATR lookback window for ``rsi-revert`` / ``atr-trail``.
        lower: RSI lower threshold for ``rsi-revert``.
        upper: RSI upper threshold for ``rsi-revert``.
        multiplier: ATR multiplier for ``atr-trail``.
        opening_range_bars: Bars that define the opening range for ``orb``
            (6 = 30 minutes of 5-minute bars).

    Raises:
        ValueError: If ``strategy_name`` is not one of the valid strategies.
    """
    if strategy_name not in _VALID_STRATEGIES:
        msg = f"strategy must be one of {list(_VALID_STRATEGIES)}, got {strategy_name!r}"
        raise ValueError(msg)

    # Load cached bars — same data seam as the existing engine.
    session_config = get_market_session_config(request.market)
    store = LocalMarketDataStore(cache_dir)
    bars = store.load_bars(request, session_config)
    if not bars:
        msg = f"no bars found in cache for {request.instrument.instrument_id} {request.timeframe}"
        raise ValueError(msg)

    # Convert to the OHLCV DataFrame that vectorbt expects.
    df = to_ohlcv_dataframe(bars)
    if df.empty:
        msg = "OHLCV DataFrame is empty after conversion"
        raise ValueError(msg)

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # Infer freq from the request timeframe if not explicitly provided.
    # Intraday data with session gaps breaks vectorbt's auto-inference.
    resolved_freq = freq or _TIMEFRAME_TO_FREQ.get(request.timeframe)

    # Generate signals and run the simulation, based on the selected strategy.
    if strategy_name == "ma-cross":
        signals = ma_cross_signals(close, fast=fast, slow=slow)
        result = run_vectorbt_backtest(
            close,
            signals.entries,
            signals.exits,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
            sl_stop=sl_stop,
            tp_stop=tp_stop,
            direction=direction,
            freq=resolved_freq,
        )
    elif strategy_name == "rsi-revert":
        signals = rsi_revert_signals(close, window=window, lower=lower, upper=upper)
        result = run_vectorbt_backtest(
            close,
            signals.entries,
            signals.exits,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
            sl_stop=sl_stop,
            tp_stop=tp_stop,
            direction=direction,
            freq=resolved_freq,
        )
    elif strategy_name == "orb":
        # ORB needs the full OHLCV DataFrame (high, low, close + index for
        # market-tz session grouping). The opening range midpoint stop is
        # encoded in the exit signal (close <= midpoint), not in sl_stop.
        signals = orb_signals(
            df,
            opening_range_bars=opening_range_bars,
        )
        result = run_vectorbt_backtest(
            close,
            signals.entries,
            signals.exits,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
            sl_stop=sl_stop,
            tp_stop=tp_stop,
            direction=direction,
            freq=resolved_freq,
        )
    else:  # atr-trail
        signals = atr_trail_signals(
            high,
            low,
            close,
            window=window,
            multiplier=multiplier,
        )
        result = run_vectorbt_backtest(
            close,
            signals.entries,
            signals.exits,
            init_cash=init_cash,
            fees=fees,
            slippage=slippage,
            # ATR trail provides its own per-bar sl_stop Series; ignore the
            # scalar sl_stop arg here and use the signal-generated one.
            sl_stop=signals.sl_stop,
            tp_stop=tp_stop,
            sl_trail=True,
            direction=direction,
            freq=resolved_freq,
        )

    return build_vectorbt_summary(
        result,
        strategy_name=strategy_name,
        output_path=output_path,
    )


__all__ = ["run_vbt_backtest"]
