"""Execution-cost stress grid: run the same backtest over a cost-scenario grid.

The grid reuses `run_minimal_backtest` from the runner and produces a compact
public-safe report keyed by scenario name. Default scenarios sweep slippage and
commission assumptions used by IBKR-style cost models.

Public surface:
    - CostStressScenario, CostStressRow, CostStressReport (re-exported from records)
    - default_cost_stress_scenarios
    - run_cost_stress_report
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from decimal import Decimal
from pathlib import Path

from trade_data import HistoricalBarsRequest
from trade_strategies import Strategy

from trade_research_app.backtest.records import (
    BacktestCostModel,
    BacktestSummary,
    CostStressReport,
    CostStressRow,
    CostStressScenario,
)


def default_cost_stress_scenarios() -> tuple[CostStressScenario, ...]:
    """Return the first standard execution-cost grid for strategy research."""
    return (
        CostStressScenario("gross", BacktestCostModel()),
        CostStressScenario(
            "commission_only",
            BacktestCostModel(commission_per_share=Decimal("0.005")),
        ),
        CostStressScenario("slippage_0_25bps", BacktestCostModel(slippage_bps=Decimal("0.25"))),
        CostStressScenario("slippage_0_5bps", BacktestCostModel(slippage_bps=Decimal("0.5"))),
        CostStressScenario("slippage_1bps", BacktestCostModel(slippage_bps=Decimal("1"))),
        CostStressScenario("slippage_2bps", BacktestCostModel(slippage_bps=Decimal("2"))),
        CostStressScenario("slippage_3bps", BacktestCostModel(slippage_bps=Decimal("3"))),
        CostStressScenario("slippage_5bps", BacktestCostModel(slippage_bps=Decimal("5"))),
        CostStressScenario(
            "slippage_1bps_commission",
            BacktestCostModel(
                slippage_bps=Decimal("1"),
                commission_per_share=Decimal("0.005"),
            ),
        ),
        CostStressScenario(
            "ibkr_ca_fixed_1bps",
            BacktestCostModel(
                slippage_bps=Decimal("1"),
                commission_per_share=Decimal("0.005"),
                minimum_commission=Decimal("1"),
            ),
        ),
        CostStressScenario(
            "ibkr_ca_tiered_1bps",
            BacktestCostModel(
                slippage_bps=Decimal("1"),
                commission_per_share=Decimal("0.0035"),
                minimum_commission=Decimal("0.35"),
            ),
        ),
    )


def run_cost_stress_report(
    *,
    request: HistoricalBarsRequest,
    cache_dir: Path,
    output_path: Path | None,
    strategy_factory: Callable[[], Strategy],
    quantity: Decimal = Decimal("1"),
    scenarios: Sequence[CostStressScenario] | None = None,
) -> CostStressReport:
    """Run the same backtest over a grid of execution-cost assumptions.

    Parameters:
        request: Provider-neutral bar request; reused for every scenario.
        cache_dir: Root directory for the local normalized bar cache.
        output_path: Optional path for the cost-stress artifact. `None` skips
            writing.
        strategy_factory: Zero-arg callable returning a fresh strategy instance
            per scenario, so each run starts from a clean strategy state.
        quantity: Fixed quantity per approved order intent.
        scenarios: Optional custom cost grid. Defaults to
            :func:`default_cost_stress_scenarios`.
    """
    # Local import avoids a circular dependency: the runner imports records, and
    # cost_stress imports the runner. Keeping `run_minimal_backtest` local keeps
    # the cost-stress module independent of the runner at import time.
    from trade_research_app.backtest.runner import run_minimal_backtest

    stress_scenarios = tuple(scenarios or default_cost_stress_scenarios())
    scenario_summaries = [
        (
            scenario,
            run_minimal_backtest(
                request=request,
                cache_dir=cache_dir,
                output_path=None,
                strategy=strategy_factory(),
                quantity=quantity,
                cost_model=scenario.cost_model,
            ),
        )
        for scenario in stress_scenarios
    ]
    gross_total_pnl = scenario_summaries[0][1].total_pnl if scenario_summaries else Decimal("0")
    rows = tuple(
        _cost_stress_row(
            scenario=scenario,
            summary=summary,
            gross_total_pnl=gross_total_pnl,
        )
        for scenario, summary in scenario_summaries
    )
    report = CostStressReport(
        strategy_name=strategy_factory().name,
        instrument_id=request.instrument.instrument_id,
        timeframe=request.timeframe,
        rows=rows,
        output_path=output_path,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report.to_json_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return report


def _cost_stress_row(
    *,
    scenario: CostStressScenario,
    summary: BacktestSummary,
    gross_total_pnl: Decimal,
) -> CostStressRow:
    """Build one compact cost-stress row from a full backtest summary."""
    cost_drag = gross_total_pnl - summary.total_pnl
    return CostStressRow(
        scenario_name=scenario.name,
        slippage_bps=scenario.cost_model.slippage_bps,
        commission_per_share=scenario.cost_model.commission_per_share,
        minimum_commission=scenario.cost_model.minimum_commission,
        closed_trades=summary.closed_trades,
        total_pnl=summary.total_pnl,
        expectancy_per_trade=summary.expectancy_per_trade,
        profit_factor=summary.profit_factor,
        total_execution_costs=summary.total_execution_costs,
        cost_drag_from_gross=cost_drag,
        gross_edge_consumed=(cost_drag / gross_total_pnl if gross_total_pnl > 0 else Decimal("0")),
        median_post_exit_max_favorable_pnl=summary.median_post_exit_max_favorable_pnl,
    )


__all__ = [
    "CostStressReport",
    "CostStressRow",
    "CostStressScenario",
    "default_cost_stress_scenarios",
    "run_cost_stress_report",
]
