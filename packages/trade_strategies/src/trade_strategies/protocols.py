"""Shared strategy interface for research and execution callers."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Protocol

from trade_core import StrategyDecision, StrategyInputRef, StrategyRunId
from trade_data import Bar


@dataclass(frozen=True, slots=True)
class StrategyDecisionContext:
    """Runner-supplied facts a strategy may use without owning execution.

    Parameters:
        strategy_run_id: Stable identifier for this backtest or future live run.
        input_ref: Shared reference to the normalized bar stream being evaluated.
        sequence_number: One-based bar number inside the current run, used for
            deterministic decision IDs in public-safe tests and reports.
        previous_bar: Last completed bar, if one exists. Simple strategies can
            compare it with the current bar without managing their own cache.
        position_quantity: Current simulated position owned by the runner. The
            strategy may use it to decide enter versus exit, but it must not
            mutate position or calculate fills.
    """

    strategy_run_id: StrategyRunId
    input_ref: StrategyInputRef
    sequence_number: int
    previous_bar: Bar | None
    position_quantity: Decimal


class Strategy(Protocol):
    """Minimal strategy seam: market input in, shared decision out.

    A strategy should describe what it wants to do, not how execution happens.
    Backtesting and future live execution can then reuse the same decision logic
    while applying different fill, broker, and reconciliation behavior.
    """

    name: ClassVar[str]

    def decide(
        self,
        *,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> StrategyDecision:
        """Evaluate one completed bar and return a shared strategy decision.

        Parameters:
            bar: Current normalized bar being evaluated.
            context: Runner-owned facts about the current run and position.
        """
        ...
