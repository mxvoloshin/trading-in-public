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


def _new_decimal_list() -> list[Decimal]:
    """Return a typed empty list for dataclass default factories."""
    return []


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
    session_open: Decimal | None = None
    first_30_minute_close: Decimal | None = None
    first_30_minute_high: Decimal | None = None
    first_30_minute_low: Decimal | None = None
    opening_window_volume: Decimal = Decimal("0")
    previous_bar: Bar | None = None
    trades_entered: int = 0
    pullback_low: Decimal | None = None
    pullback_high: Decimal | None = None
    signal_bar_low: Decimal | None = None
    consecutive_closes_below_vwap: int = 0
    true_ranges: list[Decimal] = field(default_factory=_new_decimal_list)


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
        if state.bars_seen == 1:
            state.session_open = Decimal(str(bar.open))
        if state.bars_seen <= 6:
            # Six 5-minute bars cover the 9:30-10:00 New York opening window.
            # Later strategy variants can use these values because they are
            # fully known before a 10:00-or-later entry decision.
            state.opening_window_volume += volume
            high = Decimal(str(bar.high))
            low = Decimal(str(bar.low))
            state.first_30_minute_high = (
                high
                if state.first_30_minute_high is None
                else max(state.first_30_minute_high, high)
            )
            state.first_30_minute_low = (
                low if state.first_30_minute_low is None else min(state.first_30_minute_low, low)
            )
            if state.bars_seen == 6:
                state.first_30_minute_close = Decimal(str(bar.close))
        previous_close = (
            Decimal(str(state.previous_bar.close)) if state.previous_bar is not None else None
        )
        high = Decimal(str(bar.high))
        low = Decimal(str(bar.low))
        true_range = (
            high - low
            if previous_close is None
            else max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
        state.true_ranges.append(true_range)
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


@dataclass(slots=True)
class EntryFilteredTrendDayVwapReclaimStrategy(TrendDayVwapReclaimStrategy):
    """Trend-day reclaim variant gated by entry-time trend/chop evidence.

    The full-session `trend_up` diagnostic has looked promising, but it is not
    tradable because the final session close and VWAP are unknown at entry time.
    This variant approximates that bucket with only facts already observed by
    the strategy: opening-window return, price/VWAP location, VWAP slope,
    distance from VWAP, and early participation versus prior opening windows.
    """

    name: ClassVar[str] = "trend-day-vwap-reclaim-entry-filter"

    min_first_30_minute_return: Decimal = Decimal("0")
    max_entry_distance_from_vwap: Decimal = Decimal("0.006")
    min_opening_relative_volume: Decimal = Decimal("0.85")
    relative_volume_lookback_sessions: int = 20
    _opening_window_volumes: list[Decimal] = field(
        default_factory=_new_decimal_list,
        init=False,
        repr=False,
    )

    def _state_for_bar(self, bar: Bar) -> _SessionState:
        """Reset session state while preserving prior opening-window volumes."""
        local_date = bar.timestamp_utc.astimezone(NEW_YORK).date().isoformat()
        if self._state is not None and self._state.local_date != local_date:
            self._record_completed_opening_window_volume(self._state)
        return TrendDayVwapReclaimStrategy._state_for_bar(self, bar)

    def _long_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Apply a tradable trend/chop gate before the reclaim setup."""
        gate_reason = self._entry_time_trend_gate_reason(state=state, bar=bar)
        if gate_reason is not None:
            return DecisionAction.HOLD, gate_reason
        return TrendDayVwapReclaimStrategy._long_entry_decision(self, state=state, bar=bar)

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Return the specific entry-time gate reason for filtered holds."""
        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"
        return self._long_entry_decision(state=state, bar=bar)

    def _entry_time_trend_gate_reason(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> str | None:
        """Return a reject reason when entry-time trend evidence is too weak."""
        session_open = _required_decimal(state.session_open, "session_open")
        first_30_minute_close = _required_decimal(
            state.first_30_minute_close,
            "first_30_minute_close",
        )
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        previous_vwap = _required_decimal(state.previous_vwap, "previous_vwap")
        opening_range_high = _required_decimal(
            state.opening_range_high,
            "opening_range_high",
        )
        current_close = Decimal(str(bar.close))

        first_30_minute_return = (first_30_minute_close - session_open) / session_open
        if first_30_minute_return < self.min_first_30_minute_return:
            return "entry_trend_filter_first_30_return_too_weak"
        if current_vwap <= previous_vwap:
            return "entry_trend_filter_vwap_not_rising"
        if current_close <= current_vwap:
            return "entry_trend_filter_close_not_above_vwap"
        if current_close <= opening_range_high:
            return "entry_trend_filter_close_not_above_opening_range"

        distance_from_vwap = (current_close - current_vwap) / current_vwap
        if distance_from_vwap > self.max_entry_distance_from_vwap:
            return "entry_trend_filter_entry_too_extended"

        relative_opening_volume = self._opening_relative_volume(state)
        if (
            relative_opening_volume is not None
            and relative_opening_volume < self.min_opening_relative_volume
        ):
            return "entry_trend_filter_opening_participation_too_low"

        return None

    def _opening_relative_volume(self, state: _SessionState) -> Decimal | None:
        """Compare today's completed opening-window volume with prior sessions."""
        if len(self._opening_window_volumes) < self.relative_volume_lookback_sessions:
            return None
        trailing_window = self._opening_window_volumes[-self.relative_volume_lookback_sessions :]
        baseline = sum(trailing_window, Decimal("0")) / Decimal(len(trailing_window))
        if baseline == 0:
            return None
        return state.opening_window_volume / baseline

    def _record_completed_opening_window_volume(self, state: _SessionState) -> None:
        """Store one completed 9:30-10:00 volume sample for future sessions."""
        if state.first_30_minute_close is None:
            return
        self._opening_window_volumes.append(state.opening_window_volume)


@dataclass(slots=True)
class GapAndGoVwapPullbackStrategy(EntryFilteredTrendDayVwapReclaimStrategy):
    """Positive-gap VWAP continuation candidate with early RVOL confirmation."""

    name: ClassVar[str] = "gap-and-go-vwap-pullback"

    min_gap_pct: Decimal = Decimal("0.002")
    max_gap_pct: Decimal = Decimal("0.006")
    max_opening_range_pct: Decimal = Decimal("0.01")
    _previous_session_close: Decimal | None = field(default=None, init=False, repr=False)

    def _state_for_bar(self, bar: Bar) -> _SessionState:
        """Capture the prior regular-session close before the session resets."""
        local_date = bar.timestamp_utc.astimezone(NEW_YORK).date().isoformat()
        if self._state is not None and self._state.local_date != local_date:
            previous_bar = self._state.previous_bar
            if previous_bar is not None:
                self._previous_session_close = Decimal(str(previous_bar.close))
        return EntryFilteredTrendDayVwapReclaimStrategy._state_for_bar(self, bar)

    def _entry_time_trend_gate_reason(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> str | None:
        """Require the entry-time trend gate plus positive gap-and-hold context."""
        session_open = _required_decimal(state.session_open, "session_open")
        first_30_minute_close = _required_decimal(
            state.first_30_minute_close,
            "first_30_minute_close",
        )
        first_30_minute_high = _required_decimal(
            state.first_30_minute_high,
            "first_30_minute_high",
        )
        first_30_minute_low = _required_decimal(
            state.first_30_minute_low,
            "first_30_minute_low",
        )
        current_close = Decimal(str(bar.close))

        if self._previous_session_close is None or self._previous_session_close == 0:
            return "gap_and_go_prior_close_not_ready"

        gap_pct = (session_open - self._previous_session_close) / self._previous_session_close
        if gap_pct < self.min_gap_pct:
            return "gap_and_go_positive_gap_too_small"
        if gap_pct > self.max_gap_pct:
            return "gap_and_go_positive_gap_too_large"
        if first_30_minute_close < session_open:
            return "gap_and_go_gap_failed_by_10am"
        if current_close < session_open:
            return "gap_and_go_close_lost_session_open"

        opening_range_width = (first_30_minute_high - first_30_minute_low) / session_open
        if opening_range_width > self.max_opening_range_pct:
            return "gap_and_go_opening_range_too_wide"

        parent_reason = EntryFilteredTrendDayVwapReclaimStrategy._entry_time_trend_gate_reason(
            self,
            state=state,
            bar=bar,
        )
        if parent_reason is not None:
            return parent_reason

        return None


@dataclass(slots=True)
class DailyContextVwapReclaimStrategy(EntryFilteredTrendDayVwapReclaimStrategy):
    """Entry-filtered VWAP continuation candidate gated by completed daily trend.

    The backtest currently feeds 5-minute regular-session bars, so this strategy
    derives its daily context from completed session closes already present in
    the stream. The current session's close is never used for the entry gate.
    """

    name: ClassVar[str] = "trend-day-vwap-reclaim-v2-daily-context"

    daily_sma_period: int = 20
    daily_sma_slope_lookback_sessions: int = 5
    _completed_session_closes: list[Decimal] = field(
        default_factory=_new_decimal_list,
        init=False,
        repr=False,
    )

    def _state_for_bar(self, bar: Bar) -> _SessionState:
        """Record completed regular-session closes before starting a new day."""
        local_date = bar.timestamp_utc.astimezone(NEW_YORK).date().isoformat()
        if self._state is not None and self._state.local_date != local_date:
            previous_bar = self._state.previous_bar
            if previous_bar is not None:
                self._completed_session_closes.append(Decimal(str(previous_bar.close)))
        return EntryFilteredTrendDayVwapReclaimStrategy._state_for_bar(self, bar)

    def _entry_time_trend_gate_reason(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> str | None:
        """Require bullish completed-daily context before intraday gates."""
        daily_context_reason = self._daily_context_gate_reason()
        if daily_context_reason is not None:
            return daily_context_reason
        return EntryFilteredTrendDayVwapReclaimStrategy._entry_time_trend_gate_reason(
            self,
            state=state,
            bar=bar,
        )

    def _daily_context_gate_reason(self) -> str | None:
        """Return a reject reason when completed daily trend is not supportive."""
        required_closes = self.daily_sma_period + self.daily_sma_slope_lookback_sessions
        if len(self._completed_session_closes) < required_closes:
            return "daily_context_not_ready"

        prior_regular_session_close = self._completed_session_closes[-1]
        daily_sma_20 = self._simple_moving_average(
            closes=self._completed_session_closes,
            end_offset=0,
        )
        daily_sma_20_5_sessions_ago = self._simple_moving_average(
            closes=self._completed_session_closes,
            end_offset=self.daily_sma_slope_lookback_sessions,
        )

        if prior_regular_session_close <= daily_sma_20:
            return "daily_context_prior_close_below_sma"
        if daily_sma_20 < daily_sma_20_5_sessions_ago:
            return "daily_context_sma_not_rising"
        return None

    def _simple_moving_average(
        self,
        *,
        closes: list[Decimal],
        end_offset: int,
    ) -> Decimal:
        """Calculate a daily SMA from completed session closes only."""
        end_index = len(closes) - end_offset
        start_index = end_index - self.daily_sma_period
        window = closes[start_index:end_index]
        return sum(window, Decimal("0")) / Decimal(self.daily_sma_period)


@dataclass(slots=True)
class OpeningDriveQualityVwapReclaimStrategy(DailyContextVwapReclaimStrategy):
    """Daily-context VWAP continuation candidate gated by opening drive quality.

    This variant keeps the issue #43 completed-daily context and inherited
    entry-time trend gates, then requires the first 30-minute close to land in
    the upper portion of its own high-low range. That makes the early-session
    filter stricter than "non-negative first 30-minute return" without changing
    the actual VWAP reclaim entry trigger or exits.
    """

    name: ClassVar[str] = "trend-day-vwap-reclaim-v3-opening-drive"

    min_first_30_minute_close_position: Decimal = Decimal("0.60")

    def _entry_time_trend_gate_reason(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> str | None:
        """Require opening-window close location before inherited gates."""
        daily_context_reason = self._daily_context_gate_reason()
        if daily_context_reason is not None:
            return daily_context_reason
        opening_drive_reason = self._opening_drive_quality_gate_reason(state)
        if opening_drive_reason is not None:
            return opening_drive_reason
        return EntryFilteredTrendDayVwapReclaimStrategy._entry_time_trend_gate_reason(
            self,
            state=state,
            bar=bar,
        )

    def _opening_drive_quality_gate_reason(self, state: _SessionState) -> str | None:
        """Return a reject reason when the first 30-minute drive is weak."""
        first_30_minute_close = _required_decimal(
            state.first_30_minute_close,
            "first_30_minute_close",
        )
        first_30_minute_high = _required_decimal(
            state.first_30_minute_high,
            "first_30_minute_high",
        )
        first_30_minute_low = _required_decimal(
            state.first_30_minute_low,
            "first_30_minute_low",
        )

        if first_30_minute_high == first_30_minute_low:
            close_position = Decimal("0.5")
        else:
            close_position = (first_30_minute_close - first_30_minute_low) / (
                first_30_minute_high - first_30_minute_low
            )

        if close_position < self.min_first_30_minute_close_position:
            return "opening_drive_close_position_too_weak"
        return None


@dataclass(slots=True)
class RvolBucketVwapReclaimStrategy(OpeningDriveQualityVwapReclaimStrategy):
    """Opening-drive VWAP continuation candidate gated by opening RVOL.

    This variant keeps the issue #44 daily context and opening-drive quality
    gates, then replaces the earlier lenient opening-volume gate with a stricter
    opening relative-volume threshold. The relative volume baseline uses only
    completed prior sessions.
    """

    name: ClassVar[str] = "trend-day-vwap-reclaim-v4-rvol-buckets"

    min_opening_relative_volume: Decimal = Decimal("1.00")
    relative_volume_lookback_sessions: int = 20

    def _entry_time_trend_gate_reason(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> str | None:
        """Require minimum opening RVOL before inherited entry-time gates."""
        daily_context_reason = self._daily_context_gate_reason()
        if daily_context_reason is not None:
            return daily_context_reason
        opening_drive_reason = self._opening_drive_quality_gate_reason(state)
        if opening_drive_reason is not None:
            return opening_drive_reason
        opening_rvol = self._opening_relative_volume(state)
        if opening_rvol is not None and opening_rvol < self.min_opening_relative_volume:
            return "opening_rvol_too_low"
        return EntryFilteredTrendDayVwapReclaimStrategy._entry_time_trend_gate_reason(
            self,
            state=state,
            bar=bar,
        )


@dataclass(slots=True)
class DynamicVwapDistanceReclaimStrategy(RvolBucketVwapReclaimStrategy):
    """Opening-RVOL VWAP continuation candidate with ATR-normalized distance."""

    name: ClassVar[str] = "trend-day-vwap-reclaim-v5-dynamic-vwap-distance"

    atr_period_5m: int = 20
    max_vwap_distance_atr_multiple: Decimal = Decimal("1.0")

    def _entry_time_trend_gate_reason(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> str | None:
        """Replace the fixed VWAP extension cap with a 5-minute ATR cap."""
        daily_context_reason = self._daily_context_gate_reason()
        if daily_context_reason is not None:
            return daily_context_reason
        opening_drive_reason = self._opening_drive_quality_gate_reason(state)
        if opening_drive_reason is not None:
            return opening_drive_reason
        opening_rvol = self._opening_relative_volume(state)
        if opening_rvol is not None and opening_rvol < self.min_opening_relative_volume:
            return "opening_rvol_too_low"

        session_open = _required_decimal(state.session_open, "session_open")
        first_30_minute_close = _required_decimal(
            state.first_30_minute_close,
            "first_30_minute_close",
        )
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        previous_vwap = _required_decimal(state.previous_vwap, "previous_vwap")
        opening_range_high = _required_decimal(
            state.opening_range_high,
            "opening_range_high",
        )
        current_close = Decimal(str(bar.close))

        first_30_minute_return = (first_30_minute_close - session_open) / session_open
        if first_30_minute_return < self.min_first_30_minute_return:
            return "entry_trend_filter_first_30_return_too_weak"
        if current_vwap <= previous_vwap:
            return "entry_trend_filter_vwap_not_rising"
        if current_close <= current_vwap:
            return "entry_trend_filter_close_not_above_vwap"
        if current_close <= opening_range_high:
            return "entry_trend_filter_close_not_above_opening_range"

        atr_5m = self._current_atr_5m(state)
        if atr_5m is None:
            return "dynamic_vwap_distance_atr_not_ready"
        vwap_distance = current_close - current_vwap
        max_allowed_distance = atr_5m * self.max_vwap_distance_atr_multiple
        if vwap_distance < 0:
            return "dynamic_vwap_distance_below_vwap"
        if vwap_distance > max_allowed_distance:
            return "dynamic_vwap_distance_too_extended"

        return None

    def _current_atr_5m(self, state: _SessionState) -> Decimal | None:
        """Return the current intraday 5-minute ATR if enough bars exist."""
        if len(state.true_ranges) < self.atr_period_5m:
            return None
        trailing_ranges = state.true_ranges[-self.atr_period_5m :]
        return sum(trailing_ranges, Decimal("0")) / Decimal(self.atr_period_5m)
