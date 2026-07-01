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
        average_entry_price: Current runner-owned average entry price for the
            open position, or zero when flat.
    """

    strategy_run_id: StrategyRunId
    input_ref: StrategyInputRef
    sequence_number: int
    previous_bar: Bar | None
    position_quantity: Decimal
    average_entry_price: Decimal = Decimal("0")


@dataclass(frozen=True, slots=True)
class OpenTradeDiagnostics:
    """Strategy-owned context captured at entry for R-multiple computation.

    The engine asks the strategy for this right after an opening fill. It
    contains the values the strategy set during its ``decide()`` call that
    the engine needs to compute per-trade diagnostics — most importantly
    the initial stop price (R denominator).

    Parameters:
        initial_stop_price: Stop price the strategy set at entry time. Used
            as the R denominator. Zero means no stop / R undefined.
    """

    initial_stop_price: Decimal = Decimal("0")


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


class StrategyWithDiagnostics(Protocol):
    """Strategy that also contributes per-trade diagnostics context.

    Strategies that own trade-level state useful for R-multiple computation
    (most importantly the initial stop price) implement this extended protocol.
    The engine asks the strategy for ``OpenTradeDiagnostics`` right after an
    opening fill, so the strategy can report the stop it set during ``decide()``.

    Strategies that don't need to contribute diagnostics implement only
    ``Strategy``; the engine falls back to a zero ``initial_stop_price``,
    meaning R multiples are undefined for those trades.
    """

    name: ClassVar[str]

    def decide(
        self,
        *,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> StrategyDecision:
        """Evaluate one completed bar and return a shared strategy decision."""
        ...

    def on_entry(self) -> OpenTradeDiagnostics:
        """Return diagnostics context for the trade just opened."""
        ...
