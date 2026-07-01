"""SPY 5-minute opening-range breakout baseline strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from decimal import Decimal
from typing import ClassVar
from zoneinfo import ZoneInfo

from trade_core import DecisionAction, InstrumentRef, StrategyDecision, StrategyDecisionId
from trade_data import Bar

from trade_strategies.protocols import OpenTradeDiagnostics, StrategyDecisionContext

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
    # All regular-session bars accumulated for ATR and swing calculations.
    session_bars: list[Bar] = field(default_factory=_new_bar_list)
    # Whether the trade has reached +1R favorable (for break-even and structure variants).
    reached_1r: bool = False
    # The entry price for the current open trade (set when position opens).
    entry_price: Decimal | None = None


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

    def on_entry(self) -> OpenTradeDiagnostics:
        """Return the current active stop as the R-multiple denominator.

        The stop was set during the most recent ``decide()`` call that produced
        an entry signal. By the time the engine calls this (right after the
        opening fill), ``_state.active_stop`` holds that value.
        """
        if self._state is not None and self._state.active_stop is not None:
            return OpenTradeDiagnostics(initial_stop_price=self._state.active_stop)
        return OpenTradeDiagnostics()

    def _state_for_bar(self, bar: Bar) -> _SessionState:
        """Return the current session state, resetting on a new local date."""
        local_date = bar.timestamp_utc.astimezone(NEW_YORK).date().isoformat()
        if self._state is None or self._state.local_date != local_date:
            self._state = _SessionState(local_date=local_date)
        return self._state

    def _update_opening_range(self, *, state: _SessionState, bar: Bar) -> None:
        """Capture the first six 5-minute bars as the opening range."""
        state.bars_seen += 1
        state.session_bars.append(bar)
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
            state.entry_price = close_price
            state.reached_1r = False
            return DecisionAction.ENTER_LONG, "orb_close_breakout_long"
        if close_price < opening_range_low:
            state.trades_entered += 1
            state.active_stop = self._short_stop_price(state)
            state.entry_price = close_price
            state.reached_1r = False
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


@dataclass(slots=True)
class SpyOrbBreakEvenAfter1RStrategy(SpyOpeningRangeBreakoutTrendHoldStrategy):
    """ORB variant that moves the stop to break-even after price reaches +1R.

    Entry logic is identical to the baseline. Once the trade reaches +1R
    favorable (entry_price + R for longs, entry_price - R for shorts), the
    stop moves to the entry price. If +1R is never reached, the original
    midpoint stop remains active. EOD flatten is unchanged.
    """

    name: ClassVar[str] = "spy-opening-range-breakout-trend-hold-breakeven-after-1r-max-1"
    family_name: ClassVar[str] = "spy-opening-range-breakout-trend-hold"
    variant_name: ClassVar[str] = "orb-breakeven-after-1r-max-1"
    max_trades_per_day: int = 1

    def _open_long_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        local_time: time,
    ) -> tuple[DecisionAction, str]:
        """Exit long at break-even stop (after +1R), midpoint stop, or EOD."""
        stop_price = _required_decimal(state.active_stop)
        entry_price = _required_decimal(state.entry_price)
        risk = entry_price - _required_decimal(state.opening_range_mid)
        open_price = Decimal(str(bar.open))
        low_price = Decimal(str(bar.low))
        high_price = Decimal(str(bar.high))
        close_price = Decimal(str(bar.close))

        # Check if +1R has been reached using this bar's high.
        if not state.reached_1r and risk > 0 and high_price >= entry_price + risk:
            state.reached_1r = True
            # Move stop to break-even (entry price).
            state.active_stop = entry_price
            stop_price = entry_price

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
        """Exit short at break-even stop (after +1R), midpoint stop, or EOD."""
        stop_price = _required_decimal(state.active_stop)
        entry_price = _required_decimal(state.entry_price)
        risk = _required_decimal(state.opening_range_mid) - entry_price
        open_price = Decimal(str(bar.open))
        high_price = Decimal(str(bar.high))
        low_price = Decimal(str(bar.low))
        close_price = Decimal(str(bar.close))

        # Check if +1R has been reached using this bar's low.
        if not state.reached_1r and risk > 0 and low_price <= entry_price - risk:
            state.reached_1r = True
            # Move stop to break-even (entry price).
            state.active_stop = entry_price
            stop_price = entry_price

        if high_price >= stop_price:
            stop_reference = max(open_price, stop_price)
            return DecisionAction.EXIT_SHORT, f"orb_stop_short@{stop_reference}"
        if local_time >= self.flatten_bar:
            state.active_stop = None
            return DecisionAction.EXIT_SHORT, f"orb_end_of_day_flat_short@{close_price}"
        return DecisionAction.HOLD, "holding_short_breakout"


def _strategy_atr(bars: list[Bar], period: int = 14) -> Decimal | None:
    """Calculate ATR over the latest completed session bars.

    Uses the same true-range formula as the backtest runner: max(high-low,
    |high-prev_close|, |low-prev_close|). Returns None when fewer than
    `period` bars are available.
    """
    if len(bars) < period:
        return None
    start_index = len(bars) - period
    true_ranges: list[Decimal] = []
    for index in range(start_index, len(bars)):
        bar = bars[index]
        high = Decimal(str(bar.high))
        low = Decimal(str(bar.low))
        previous_close = Decimal(str(bars[index - 1].close)) if index > 0 else None
        true_range = (
            high - low
            if previous_close is None
            else max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
        true_ranges.append(true_range)
    return sum(true_ranges, Decimal("0")) / Decimal(period)


@dataclass(slots=True)
class SpyOrbAtrTrailStrategy(SpyOpeningRangeBreakoutTrendHoldStrategy):
    """ORB variant with an ATR-based trailing stop.

    Entry logic is identical to the baseline. After entry, the stop is set
    at entry ± `atr_multiplier` * ATR(14). Each new bar ratchets the stop:
    for longs, new_stop = max(current_stop, bar.high - multiplier * ATR);
    for shorts, new_stop = min(current_stop, bar.low + multiplier * ATR).
    Before 14 bars are available, the midpoint stop is used as a fallback.
    EOD flatten is unchanged.
    """

    atr_multiplier: Decimal = Decimal("1.0")

    def _open_long_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        local_time: time,
    ) -> tuple[DecisionAction, str]:
        """Exit long at ATR trail stop or EOD."""
        open_price = Decimal(str(bar.open))
        low_price = Decimal(str(bar.low))
        high_price = Decimal(str(bar.high))
        close_price = Decimal(str(bar.close))

        # Ratchet the trailing stop using this bar's high.
        atr = _strategy_atr(state.session_bars, period=14)
        if atr is not None and state.active_stop is not None:
            new_stop = high_price - self.atr_multiplier * atr
            # The stop only moves up (ratchets) for a long position.
            state.active_stop = max(state.active_stop, new_stop)

        stop_price = _required_decimal(state.active_stop)
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
        """Exit short at ATR trail stop or EOD."""
        open_price = Decimal(str(bar.open))
        high_price = Decimal(str(bar.high))
        low_price = Decimal(str(bar.low))
        close_price = Decimal(str(bar.close))

        # Ratchet the trailing stop using this bar's low.
        atr = _strategy_atr(state.session_bars, period=14)
        if atr is not None and state.active_stop is not None:
            new_stop = low_price + self.atr_multiplier * atr
            # The stop only moves down (ratchets) for a short position.
            state.active_stop = min(state.active_stop, new_stop)

        stop_price = _required_decimal(state.active_stop)
        if high_price >= stop_price:
            stop_reference = max(open_price, stop_price)
            return DecisionAction.EXIT_SHORT, f"orb_stop_short@{stop_reference}"
        if local_time >= self.flatten_bar:
            state.active_stop = None
            return DecisionAction.EXIT_SHORT, f"orb_end_of_day_flat_short@{close_price}"
        return DecisionAction.HOLD, "holding_short_breakout"


@dataclass(slots=True)
class SpyOrbAtrTrail1_0Strategy(SpyOrbAtrTrailStrategy):
    """ORB ATR trailing stop with 1.0 ATR multiplier."""

    name: ClassVar[str] = "spy-opening-range-breakout-trend-hold-atr-trail-1-0-max-1"
    family_name: ClassVar[str] = "spy-opening-range-breakout-trend-hold"
    variant_name: ClassVar[str] = "orb-atr-trail-1-0-max-1"
    max_trades_per_day: int = 1
    atr_multiplier: Decimal = Decimal("1.0")


@dataclass(slots=True)
class SpyOrbAtrTrail1_5Strategy(SpyOrbAtrTrailStrategy):
    """ORB ATR trailing stop with 1.5 ATR multiplier."""

    name: ClassVar[str] = "spy-opening-range-breakout-trend-hold-atr-trail-1-5-max-1"
    family_name: ClassVar[str] = "spy-opening-range-breakout-trend-hold"
    variant_name: ClassVar[str] = "orb-atr-trail-1-5-max-1"
    max_trades_per_day: int = 1
    atr_multiplier: Decimal = Decimal("1.5")


@dataclass(slots=True)
class SpyOrbAtrTrail2_0Strategy(SpyOrbAtrTrailStrategy):
    """ORB ATR trailing stop with 2.0 ATR multiplier."""

    name: ClassVar[str] = "spy-opening-range-breakout-trend-hold-atr-trail-2-0-max-1"
    family_name: ClassVar[str] = "spy-opening-range-breakout-trend-hold"
    variant_name: ClassVar[str] = "orb-atr-trail-2-0-max-1"
    max_trades_per_day: int = 1
    atr_multiplier: Decimal = Decimal("2.0")


@dataclass(slots=True)
class SpyOrbStructureTrailStrategy(SpyOpeningRangeBreakoutTrendHoldStrategy):
    """ORB variant that trails using recent swing structure after +1R.

    Entry logic is identical to the baseline. Before +1R is reached, the
    midpoint stop is used. After +1R, the stop trails to the most recent
    swing low (long) or swing high (short), defined as the extreme of the
    last 3 completed bars. The trail ratchets in the favorable direction.
    EOD flatten is unchanged.
    """

    name: ClassVar[str] = "spy-opening-range-breakout-trend-hold-structure-trail-after-1r-max-1"
    family_name: ClassVar[str] = "spy-opening-range-breakout-trend-hold"
    variant_name: ClassVar[str] = "orb-structure-trail-after-1r-max-1"
    max_trades_per_day: int = 1
    swing_lookback: int = 3

    def _open_long_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        local_time: time,
    ) -> tuple[DecisionAction, str]:
        """Exit long at structure trail stop (after +1R), midpoint stop, or EOD."""
        stop_price = _required_decimal(state.active_stop)
        entry_price = _required_decimal(state.entry_price)
        risk = entry_price - _required_decimal(state.opening_range_mid)
        open_price = Decimal(str(bar.open))
        low_price = Decimal(str(bar.low))
        high_price = Decimal(str(bar.high))
        close_price = Decimal(str(bar.close))

        # Check if +1R has been reached using this bar's high.
        if not state.reached_1r and risk > 0 and high_price >= entry_price + risk:
            state.reached_1r = True
            # Switch to structure trail: use swing low of last N bars.
            swing_low = self._swing_low(state)
            if swing_low is not None:
                state.active_stop = max(_required_decimal(state.active_stop), swing_low)

        # Continue trailing with swing low while +1R has been reached.
        if state.reached_1r:
            swing_low = self._swing_low(state)
            if swing_low is not None:
                state.active_stop = max(_required_decimal(state.active_stop), swing_low)

        stop_price = _required_decimal(state.active_stop)
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
        """Exit short at structure trail stop (after +1R), midpoint stop, or EOD."""
        stop_price = _required_decimal(state.active_stop)
        entry_price = _required_decimal(state.entry_price)
        risk = _required_decimal(state.opening_range_mid) - entry_price
        open_price = Decimal(str(bar.open))
        high_price = Decimal(str(bar.high))
        low_price = Decimal(str(bar.low))
        close_price = Decimal(str(bar.close))

        # Check if +1R has been reached using this bar's low.
        if not state.reached_1r and risk > 0 and low_price <= entry_price - risk:
            state.reached_1r = True
            # Switch to structure trail: use swing high of last N bars.
            swing_high = self._swing_high(state)
            if swing_high is not None:
                state.active_stop = min(_required_decimal(state.active_stop), swing_high)

        # Continue trailing with swing high while +1R has been reached.
        if state.reached_1r:
            swing_high = self._swing_high(state)
            if swing_high is not None:
                state.active_stop = min(_required_decimal(state.active_stop), swing_high)

        stop_price = _required_decimal(state.active_stop)
        if high_price >= stop_price:
            stop_reference = max(open_price, stop_price)
            return DecisionAction.EXIT_SHORT, f"orb_stop_short@{stop_reference}"
        if local_time >= self.flatten_bar:
            state.active_stop = None
            return DecisionAction.EXIT_SHORT, f"orb_end_of_day_flat_short@{close_price}"
        return DecisionAction.HOLD, "holding_short_breakout"

    def _swing_low(self, state: _SessionState) -> Decimal | None:
        """Return the lowest low of the last N completed session bars."""
        if len(state.session_bars) < self.swing_lookback:
            return None
        recent = state.session_bars[-self.swing_lookback :]
        return min(Decimal(str(bar.low)) for bar in recent)

    def _swing_high(self, state: _SessionState) -> Decimal | None:
        """Return the highest high of the last N completed session bars."""
        if len(state.session_bars) < self.swing_lookback:
            return None
        recent = state.session_bars[-self.swing_lookback :]
        return max(Decimal(str(bar.high)) for bar in recent)
