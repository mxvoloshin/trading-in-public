"""Backtest package: runner, records, and cost-stress grid.

The public surface (`run_minimal_backtest`, `run_cost_stress_report`,
`default_cost_stress_scenarios`, `BacktestCostModel`, `BacktestSummary`,
`session_regime_tags`, ...) is re-exported here so callers can keep importing
from `trade_research_app.backtest` as before. The implementation is split into:

    - records:     pure value objects (fills, closed trades, summary, cost models)
    - cost_stress: execution-cost stress grid
    - runner:      bar-by-bar engine + post-trade enrichment + summary assembly
"""

from __future__ import annotations

from trade_analytics.metrics import ClosedTrade
from trade_analytics.session_regimes import session_regime_tags

from trade_research_app.backtest.cost_stress import (
    default_cost_stress_scenarios,
    run_cost_stress_report,
)
from trade_research_app.backtest.records import (
    BacktestCostModel,
    BacktestSummary,
    CostStressReport,
    CostStressRow,
    CostStressScenario,
    SimulatedFill,
)
from trade_research_app.backtest.runner import (
    run_minimal_backtest,
)

__all__ = [
    "BacktestCostModel",
    "BacktestSummary",
    "ClosedTrade",
    "CostStressReport",
    "CostStressRow",
    "CostStressScenario",
    "SimulatedFill",
    "default_cost_stress_scenarios",
    "run_cost_stress_report",
    "run_minimal_backtest",
    "session_regime_tags",
]
