"""SPY 5-minute opening-range breakout baseline strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal
from typing import ClassVar
from zoneinfo import ZoneInfo

from trade_core import DecisionAction, InstrumentRef, StrategyDecision, StrategyDecisionId
from trade_data import Bar

from trade_strategies.protocols import StrategyDecisionContext

NEW_YORK = ZoneInfo("America/New_York")


def _new_bar_list() -> list[Bar]:
    """Return a typed empty list for session-state defaults."""
    return []


@dataclass(slots=True)
class _SessionState:
    """Mutable session-scoped state reset at each New York trading date."""

    local_date: str
    bars_seen: int = 0
    trades_entered: int = 0
    opening_range_high: Decimal | None = None
    opening_range_low: Decimal | None = None
    opening_range_open: Decimal | None = None
    opening_range_close: Decimal | None = None
    opening_range_mid: Decimal | None = None
    active_stop: Decimal | None = None
    opening_bars: list[Bar] = field(default_factory=_new_bar_list)


@dataclass(slots=True)
class SpyOpeningRangeBreakoutTrendHoldStrategy:
    """Baseline SPY ORB strategy that holds until stop or end of day.

    The baseline intentionally stays simple:

    - use the first 30 regular-session minutes as the opening range
    - wait for a completed-bar breakout after 10:00 New York time
    - enter on the next bar open through the shared runner model
    - use the opening-range midpoint as the stop
    - force flat into the 15:55-16:00 bar close
    """

    name: ClassVar[str] = "spy-opening-range-breakout-trend-hold-midpoint-stop-max-1"
    family_name: ClassVar[str] = "spy-opening-range-breakout-trend-hold"
    variant_name: ClassVar[str] = "orb-midpoint-stop-max-1"

    max_trades_per_day: int = 1
    entry_start: time = time(10, 0)
    last_entry_bar: time = time(14, 30)
    flatten_bar: time = time(15, 55)
    _state: _SessionState | None = field(default=None, init=False, repr=False)

    def decide(
        self,
        *,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> StrategyDecision:
        """Evaluate one completed bar and emit an ORB decision."""
        state = self._state_for_bar(bar)
        self._update_opening_range(state=state, bar=bar)
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()

        action = DecisionAction.HOLD
        reason = "waiting_for_opening_range"

        if context.position_quantity > 0:
            action, reason = self._open_long_decision(state=state, bar=bar, local_time=local_time)
        elif context.position_quantity < 0:
            action, reason = self._open_short_decision(
                state=state,
                bar=bar,
                local_time=local_time,
            )
        else:
            state.active_stop = None
            action, reason = self._flat_position_decision(
                state=state,
                bar=bar,
                local_time=local_time,
            )

        return self._decision(action=action, bar=bar, context=context, reason=reason)

    def _state_for_bar(self, bar: Bar) -> _SessionState:
        """Return the current session state, resetting on a new local date."""
        local_date = bar.timestamp_utc.astimezone(NEW_YORK).date().isoformat()
        if self._state is None or self._state.local_date != local_date:
            self._state = _SessionState(local_date=local_date)
        return self._state

    def _update_opening_range(self, *, state: _SessionState, bar: Bar) -> None:
        """Capture the first six 5-minute bars as the opening range."""
        state.bars_seen += 1
        if state.bars_seen > 6:
            return

        state.opening_bars.append(bar)
        high = Decimal(str(bar.high))
        low = Decimal(str(bar.low))
        if state.opening_range_open is None:
            state.opening_range_open = Decimal(str(bar.open))
        state.opening_range_high = (
            high if state.opening_range_high is None else max(state.opening_range_high, high)
        )
        state.opening_range_low = (
            low if state.opening_range_low is None else min(state.opening_range_low, low)
        )
        if state.bars_seen == 6:
            state.opening_range_close = Decimal(str(bar.close))
            state.opening_range_mid = (
                _required_decimal(state.opening_range_high)
                + _required_decimal(state.opening_range_low)
            ) / Decimal("2")

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        local_time: time,
    ) -> tuple[DecisionAction, str]:
        """Evaluate completed-bar breakouts while flat."""
        if not self._entry_context_ready(state=state, local_time=local_time):
            return DecisionAction.HOLD, "entry_context_not_ready"

        opening_range_high = _required_decimal(state.opening_range_high)
        opening_range_low = _required_decimal(state.opening_range_low)
        close_price = Decimal(str(bar.close))

        if close_price > opening_range_high:
            state.trades_entered += 1
            state.active_stop = self._long_stop_price(state)
            return DecisionAction.ENTER_LONG, "orb_close_breakout_long"
        if close_price < opening_range_low:
            state.trades_entered += 1
            state.active_stop = self._short_stop_price(state)
            return DecisionAction.ENTER_SHORT, "orb_close_breakout_short"
        return DecisionAction.HOLD, "breakout_not_confirmed"

    def _open_long_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        local_time: time,
    ) -> tuple[DecisionAction, str]:
        """Exit long trades at the stop or the end-of-day close."""
        stop_price = _required_decimal(state.active_stop)
        open_price = Decimal(str(bar.open))
        low_price = Decimal(str(bar.low))
        close_price = Decimal(str(bar.close))

        if low_price <= stop_price:
            stop_reference = min(open_price, stop_price)
            return DecisionAction.EXIT_LONG, f"orb_stop_long@{stop_reference}"
        if local_time >= self.flatten_bar:
            state.active_stop = None
            return DecisionAction.EXIT_LONG, f"orb_end_of_day_flat_long@{close_price}"
        return DecisionAction.HOLD, "holding_long_breakout"

    def _open_short_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        local_time: time,
    ) -> tuple[DecisionAction, str]:
        """Exit short trades at the stop or the end-of-day close."""
        stop_price = _required_decimal(state.active_stop)
        open_price = Decimal(str(bar.open))
        high_price = Decimal(str(bar.high))
        close_price = Decimal(str(bar.close))

        if high_price >= stop_price:
            stop_reference = max(open_price, stop_price)
            return DecisionAction.EXIT_SHORT, f"orb_stop_short@{stop_reference}"
        if local_time >= self.flatten_bar:
            state.active_stop = None
            return DecisionAction.EXIT_SHORT, f"orb_end_of_day_flat_short@{close_price}"
        return DecisionAction.HOLD, "holding_short_breakout"

    def _entry_context_ready(self, *, state: _SessionState, local_time: time) -> bool:
        """Return whether the current bar is eligible to create a new entry."""
        if state.bars_seen < 6:
            return False
        if local_time < self.entry_start or local_time > self.last_entry_bar:
            return False
        return state.trades_entered < self.max_trades_per_day

    def _long_stop_price(self, state: _SessionState) -> Decimal:
        """Return the configured initial stop for long breakouts."""
        return _required_decimal(state.opening_range_mid)

    def _short_stop_price(self, state: _SessionState) -> Decimal:
        """Return the configured initial stop for short breakouts."""
        return _required_decimal(state.opening_range_mid)

    def _decision(
        self,
        *,
        action: DecisionAction,
        bar: Bar,
        context: StrategyDecisionContext,
        reason: str,
    ) -> StrategyDecision:
        """Build a shared decision with deterministic IDs and traceability."""
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


def _required_decimal(value: Decimal | None) -> Decimal:
    """Return a required Decimal session value or fail loudly."""
    if value is None:
        msg = "required opening-range value is missing"
        raise ValueError(msg)
    return value


@dataclass(slots=True)
class SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy(SpyOpeningRangeBreakoutTrendHoldStrategy):
    """ORB baseline with midpoint stop and one trade per day."""

    name: ClassVar[str] = "spy-opening-range-breakout-trend-hold-midpoint-stop-max-1"
    family_name: ClassVar[str] = "spy-opening-range-breakout-trend-hold"
    variant_name: ClassVar[str] = "orb-midpoint-stop-max-1"
    max_trades_per_day: int = 1
