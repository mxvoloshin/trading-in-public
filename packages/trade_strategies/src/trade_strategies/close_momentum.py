"""Tiny reusable strategy used by the first backtest runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from trade_core import (
    DecisionAction,
    InstrumentRef,
    StrategyDecision,
    StrategyDecisionId,
)
from trade_data import Bar

from trade_strategies.protocols import StrategyDecisionContext


@dataclass(frozen=True, slots=True)
class CloseMomentumStrategy:
    """Enter long when the close rises, exit when the close falls.

    This is intentionally simple. Its job is to prove that strategy code can emit
    shared `trade_core` decisions while the backtest app owns simulated execution.
    """

    name: ClassVar[str] = "close-momentum"

    def decide(
        self,
        *,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> StrategyDecision:
        """Evaluate the current bar against the previous close.

        Parameters:
            bar: Current completed bar. The strategy reads its close but does not
                decide where or when orders are filled.
            context: Runner-supplied previous bar, position, trace IDs, and input
                reference needed to produce a shared `StrategyDecision`.
        """
        previous_bar = context.previous_bar
        action = DecisionAction.HOLD
        reason = "waiting_for_previous_bar"

        if previous_bar is not None:
            # This strategy is intentionally position-aware but not
            # execution-aware: it asks to enter/exit, while the runner decides
            # whether that request becomes an order intent and simulated fill.
            if context.position_quantity == 0 and bar.close > previous_bar.close:
                action = DecisionAction.ENTER_LONG
                reason = "close_above_previous_close"
            elif context.position_quantity > 0 and bar.close < previous_bar.close:
                action = DecisionAction.EXIT_LONG
                reason = "close_below_previous_close"
            else:
                reason = "no_position_change"

        # Stable IDs make local reports and tests deterministic while still using
        # the shared traceability contract from `trade_core`.
        decision_id = StrategyDecisionId(
            f"{context.strategy_run_id.value}-strategy-decision-{context.sequence_number:04d}"
        )
        instrument = InstrumentRef(
            instrument_id=bar.instrument_id,
            market=context.input_ref.instrument.market,
            currency=context.input_ref.instrument.currency,
        )
        return StrategyDecision(
            strategy_run_id=context.strategy_run_id,
            strategy_name=self.name,
            action=action,
            input_refs=(context.input_ref,),
            reason=f"{reason}:{instrument.instrument_id}",
            decided_at_utc=context.input_ref.observed_at_utc,
            strategy_decision_id=decision_id,
        )
