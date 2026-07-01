"""Backtest runner shim.

The engine lives in ``backtest.engine``; this module re-exports the public
entry point so callers that imported ``run_minimal_backtest`` from
``backtest.runner`` keep working. New code should import from
``backtest.engine`` directly.
"""

from __future__ import annotations

from trade_research_app.backtest.engine import run_minimal_backtest

__all__ = ["run_minimal_backtest"]
