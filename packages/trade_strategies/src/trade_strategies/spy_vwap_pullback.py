"""SPY 5-minute VWAP pullback strategy candidate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal
from typing import ClassVar
from zoneinfo import ZoneInfo

from trade_core import (
    DecisionAction,
    InstrumentRef,
    StrategyDecision,
    StrategyDecisionId,
)
from trade_data import Bar

from trade_strategies.protocols import StrategyDecisionContext

NEW_YORK = ZoneInfo("America/New_York")


@dataclass(slots=True)
class _SessionState:
    """Mutable intraday facts reset at each New York trading date."""

    local_date: str
    bars_seen: int = 0
    opening_range_high: Decimal | None = None
    opening_range_low: Decimal | None = None
    cumulative_price_volume: Decimal = Decimal("0")
    cumulative_volume: Decimal = Decimal("0")
    current_vwap: Decimal | None = None
    previous_vwap: Decimal | None = None
    previous_bar: Bar | None = None
    trades_entered: int = 0
    pullback_low: Decimal | None = None
    pullback_high: Decimal | None = None
    signal_bar_low: Decimal | None = None
    consecutive_closes_below_vwap: int = 0


@dataclass(slots=True)
class SpyVwapPullbackStrategy:
    """Long-only SPY VWAP pullback candidate for the v1 live strategy research.

    The strategy models the decision rules from the project research note in a
    deliberately mechanical form that can be backtested:

    - use regular-session 5-minute SPY bars
    - build session VWAP from intraday OHLCV
    - use the first bar as the opening range
    - wait until the first 30 minutes have passed
    - enter only when price is above VWAP and the opening range high
    - require a pullback toward VWAP followed by trend resumption
    - exit on VWAP failure, structure failure, or end-of-day flat timing

    This is a research candidate, not a live-trading approval.
    """

    name: ClassVar[str] = "spy-vwap-pullback"
    allow_short: ClassVar[bool] = False

    max_trades_per_day: int = 2
    min_bars_before_entry: int = 6
    pullback_tolerance: Decimal = Decimal("0.0015")
    no_new_entries_after: time = time(15, 30)
    flatten_from: time = time(15, 45)
    _state: _SessionState | None = field(default=None, init=False, repr=False)

    def decide(
        self,
        *,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> StrategyDecision:
        """Evaluate one completed bar and emit a shared strategy decision.

        Parameters:
            bar: Current completed strategy-facing OHLCV bar.
            context: Runner-owned trace information and simulated position.
        """
        state = self._state_for_bar(bar)
        self._update_vwap(state, bar)
        action = DecisionAction.HOLD
        reason = "waiting_for_setup"

        if state.bars_seen == 1:
            # The first regular-session 5-minute bar defines the opening range.
            # Later bars can use it as a directional filter without the runner
            # needing any strategy-specific knowledge.
            state.opening_range_high = Decimal(str(bar.high))
            state.opening_range_low = Decimal(str(bar.low))
            reason = "opening_range_seeded"
        elif context.position_quantity > 0:
            action, reason = self._open_long_decision(state=state, bar=bar)
        elif context.position_quantity < 0:
            action, reason = self._open_short_decision(state=state, bar=bar)
        else:
            action, reason = self._flat_position_decision(state=state, bar=bar)

        state.previous_bar = bar
        return self._decision(
            action=action,
            bar=bar,
            context=context,
            reason=reason,
        )

    def _state_for_bar(self, bar: Bar) -> _SessionState:
        """Return the current session state, resetting on a new local date."""
        local_date = bar.timestamp_utc.astimezone(NEW_YORK).date().isoformat()
        if self._state is None or self._state.local_date != local_date:
            self._state = _SessionState(local_date=local_date)
        return self._state

    def _update_vwap(self, state: _SessionState, bar: Bar) -> None:
        """Update session VWAP using typical price weighted by bar volume."""
        typical_price = (
            Decimal(str(bar.high)) + Decimal(str(bar.low)) + Decimal(str(bar.close))
        ) / Decimal("3")
        volume = Decimal(bar.volume)
        state.bars_seen += 1
        state.cumulative_price_volume += typical_price * volume
        state.cumulative_volume += volume
        state.previous_vwap = state.current_vwap
        if state.cumulative_volume > 0:
            state.current_vwap = state.cumulative_price_volume / state.cumulative_volume

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Decide whether a flat strategy should request a directional entry."""
        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"

        long_action, long_reason = self._long_entry_decision(state=state, bar=bar)
        if long_action != DecisionAction.HOLD:
            return long_action, long_reason
        if self.allow_short:
            short_action, short_reason = self._short_entry_decision(state=state, bar=bar)
            if short_action != DecisionAction.HOLD:
                return short_action, short_reason
        return DecisionAction.HOLD, "pullback_entry_filter_not_met"

    def _long_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Decide whether a flat strategy should request a long entry."""
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        previous_vwap = _required_decimal(state.previous_vwap, "previous_vwap")
        opening_range_high = _required_decimal(
            state.opening_range_high,
            "opening_range_high",
        )
        previous_bar = _required_bar(state.previous_bar)

        previous_low = Decimal(str(previous_bar.low))
        previous_close = Decimal(str(previous_bar.close))
        current_close = Decimal(str(bar.close))
        current_open = Decimal(str(bar.open))
        current_high = Decimal(str(bar.high))

        # A pullback is useful only if it gets close enough to VWAP without
        # turning into a full VWAP failure. The tolerance keeps the rule from
        # requiring an exact touch, which would be too brittle on 5-minute bars.
        pullback_near_vwap = previous_low <= current_vwap * (Decimal("1") + self.pullback_tolerance)
        pullback_held_vwap = previous_close >= previous_vwap * (
            Decimal("1") - self.pullback_tolerance
        )
        trend_resumed = current_close > Decimal(str(previous_bar.high)) and (
            current_close > current_open
        )

        if (
            current_vwap > previous_vwap
            and current_close > current_vwap
            and current_high > opening_range_high
            and pullback_near_vwap
            and pullback_held_vwap
            and trend_resumed
        ):
            state.trades_entered += 1
            state.pullback_low = previous_low
            return DecisionAction.ENTER_LONG, "vwap_pullback_resumed_above_opening_range"

        return DecisionAction.HOLD, "long_pullback_entry_filter_not_met"

    def _short_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Decide whether a flat strategy should request a short entry."""
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        previous_vwap = _required_decimal(state.previous_vwap, "previous_vwap")
        opening_range_low = _required_decimal(
            state.opening_range_low,
            "opening_range_low",
        )
        previous_bar = _required_bar(state.previous_bar)

        previous_high = Decimal(str(previous_bar.high))
        previous_close = Decimal(str(previous_bar.close))
        current_close = Decimal(str(bar.close))
        current_open = Decimal(str(bar.open))
        current_low = Decimal(str(bar.low))

        # Mirror the long pullback rule: a bearish retest should get close to
        # VWAP from below without fully reclaiming it, then resume lower.
        retest_near_vwap = previous_high >= current_vwap * (Decimal("1") - self.pullback_tolerance)
        retest_held_vwap = previous_close <= previous_vwap * (
            Decimal("1") + self.pullback_tolerance
        )
        trend_resumed = current_close < Decimal(str(previous_bar.low)) and (
            current_close < current_open
        )

        if (
            current_vwap < previous_vwap
            and current_close < current_vwap
            and current_low < opening_range_low
            and retest_near_vwap
            and retest_held_vwap
            and trend_resumed
        ):
            state.trades_entered += 1
            state.pullback_high = previous_high
            return DecisionAction.ENTER_SHORT, "vwap_retest_resumed_below_opening_range"

        return DecisionAction.HOLD, "short_retest_entry_filter_not_met"

    def _open_long_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Decide whether an open long should exit."""
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()
        current_close = Decimal(str(bar.close))
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")

        if local_time >= self.flatten_from:
            return DecisionAction.EXIT_LONG, "end_of_day_flatten"
        if current_close < current_vwap:
            return DecisionAction.EXIT_LONG, "close_below_vwap"
        if state.pullback_low is not None and current_close < state.pullback_low:
            return DecisionAction.EXIT_LONG, "pullback_structure_failed"

        return DecisionAction.HOLD, "long_thesis_still_valid"

    def _open_short_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Decide whether an open short should exit."""
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()
        current_close = Decimal(str(bar.close))
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")

        if local_time >= self.flatten_from:
            return DecisionAction.EXIT_SHORT, "end_of_day_flatten"
        if current_close > current_vwap:
            return DecisionAction.EXIT_SHORT, "close_above_vwap"
        if state.pullback_high is not None and current_close > state.pullback_high:
            return DecisionAction.EXIT_SHORT, "short_pullback_structure_failed"

        return DecisionAction.HOLD, "short_thesis_still_valid"

    def _has_entry_context(self, *, state: _SessionState, bar: Bar) -> bool:
        """Return whether enough session context exists to consider entries."""
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()
        if state.bars_seen <= self.min_bars_before_entry:
            return False
        if local_time >= self.no_new_entries_after:
            return False
        if state.trades_entered >= self.max_trades_per_day:
            return False
        if state.current_vwap is None or state.previous_vwap is None:
            return False
        return state.opening_range_high is not None and state.previous_bar is not None

    def _decision(
        self,
        *,
        action: DecisionAction,
        bar: Bar,
        context: StrategyDecisionContext,
        reason: str,
    ) -> StrategyDecision:
        """Build the shared immutable strategy decision record."""
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


def _required_decimal(value: Decimal | None, label: str) -> Decimal:
    """Return a calculated decimal or fail loudly if strategy state is inconsistent."""
    if value is None:
        msg = f"{label} is required before evaluating this strategy rule"
        raise RuntimeError(msg)
    return value


def _required_bar(value: Bar | None) -> Bar:
    """Return a previous bar or fail loudly if entry context was mischecked."""
    if value is None:
        msg = "previous_bar is required before evaluating this strategy rule"
        raise RuntimeError(msg)
    return value


@dataclass(slots=True)
class SymmetricSpyVwapPullbackStrategy(SpyVwapPullbackStrategy):
    """Long and short SPY VWAP pullback candidate for trend-continuation research."""

    name: ClassVar[str] = "spy-vwap-pullback-long-short"
    allow_short: ClassVar[bool] = True


@dataclass(slots=True)
class TrendDayVwapReclaimStrategy(SpyVwapPullbackStrategy):
    """Long-only trend-day VWAP reclaim candidate.

    This variant narrows the original pullback idea. It looks for an established
    intraday uptrend, waits for a VWAP retest, and enters only when price
    reclaims VWAP with renewed upside momentum. It remains a research candidate,
    not a live-trading approval.
    """

    name: ClassVar[str] = "trend-day-vwap-reclaim"

    max_trades_per_day: int = 1
    no_new_entries_before: time = time(10, 0)
    no_new_entries_after: time = time(14, 30)
    flatten_from: time = time(15, 45)

    def _long_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Request a long only after a trend-day VWAP retest/reclaim."""
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        previous_vwap = _required_decimal(state.previous_vwap, "previous_vwap")
        opening_range_high = _required_decimal(
            state.opening_range_high,
            "opening_range_high",
        )
        previous_bar = _required_bar(state.previous_bar)

        previous_low = Decimal(str(previous_bar.low))
        previous_close = Decimal(str(previous_bar.close))
        current_close = Decimal(str(bar.close))
        current_low = Decimal(str(bar.low))

        retested_vwap = previous_low <= previous_vwap * (Decimal("1") + self.pullback_tolerance)
        reclaimed_vwap = (
            current_low <= current_vwap * (Decimal("1") + self.pullback_tolerance)
            and current_close > current_vwap
        )
        trend_day_context = current_close > opening_range_high and current_vwap > previous_vwap
        momentum_resumed = current_close > previous_close

        if retested_vwap and reclaimed_vwap and trend_day_context and momentum_resumed:
            state.trades_entered += 1
            state.signal_bar_low = Decimal(str(bar.low))
            state.consecutive_closes_below_vwap = 0
            return DecisionAction.ENTER_LONG, "trend_day_vwap_reclaim"

        return DecisionAction.HOLD, "trend_day_reclaim_filter_not_met"

    def _open_long_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Exit trend-day reclaim trades on VWAP loss, signal failure, or EOD."""
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()
        current_close = Decimal(str(bar.close))
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")

        if local_time >= self.flatten_from:
            return DecisionAction.EXIT_LONG, "end_of_day_flatten"
        if state.signal_bar_low is not None and current_close < state.signal_bar_low:
            return DecisionAction.EXIT_LONG, "close_below_signal_bar_low"

        if current_close < current_vwap:
            state.consecutive_closes_below_vwap += 1
            if state.consecutive_closes_below_vwap >= 2:
                return DecisionAction.EXIT_LONG, "two_closes_below_vwap"
            return DecisionAction.HOLD, "first_close_below_vwap"

        state.consecutive_closes_below_vwap = 0
        return DecisionAction.HOLD, "trend_day_reclaim_still_valid"

    def _has_entry_context(self, *, state: _SessionState, bar: Bar) -> bool:
        """Return whether the trend-day candidate can consider a new entry."""
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()
        if local_time < self.no_new_entries_before:
            return False
        return SpyVwapPullbackStrategy._has_entry_context(self, state=state, bar=bar)
