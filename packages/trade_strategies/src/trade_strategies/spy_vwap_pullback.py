"""SPY 5-minute VWAP pullback strategy candidate."""

from __future__ import annotations

from collections.abc import Sequence
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
    session_high: Decimal | None = None
    session_low: Decimal | None = None
    first_30_minute_close: Decimal | None = None
    first_30_minute_high: Decimal | None = None
    first_30_minute_low: Decimal | None = None
    opening_window_volume: Decimal = Decimal("0")
    previous_bar: Bar | None = None
    trades_entered: int = 0
    pullback_low: Decimal | None = None
    pullback_high: Decimal | None = None
    signal_bar_low: Decimal | None = None
    signal_bar_high: Decimal | None = None
    signal_bar_vwap: Decimal | None = None
    signal_bar_atr_5m: Decimal | None = None
    initial_stop: Decimal | None = None
    initial_risk: Decimal | None = None
    initial_target: Decimal | None = None
    open_trade_bars_held: int = 0
    max_open_r_since_entry: Decimal | None = None
    pending_break_side: str | None = None
    pending_break_signal_low: Decimal | None = None
    pending_break_signal_high: Decimal | None = None
    pending_break_bars_remaining: int = 0
    consecutive_closes_below_vwap: int = 0
    true_ranges: list[Decimal] = field(default_factory=_new_decimal_list)
    range_reversion_bars: tuple[Bar, ...] = ()


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
        high = Decimal(str(bar.high))
        low = Decimal(str(bar.low))
        state.session_high = high if state.session_high is None else max(state.session_high, high)
        state.session_low = low if state.session_low is None else min(state.session_low, low)
        if state.bars_seen <= 6:
            # Six 5-minute bars cover the 9:30-10:00 New York opening window.
            # Later strategy variants can use these values because they are
            # fully known before a 10:00-or-later entry decision.
            state.opening_window_volume += volume
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


def _simple_moving_average(
    *,
    closes: list[Decimal],
    period: int,
    end_offset: int,
) -> Decimal:
    """Calculate an SMA from completed session closes only."""
    end_index = len(closes) - end_offset
    start_index = end_index - period
    window = closes[start_index:end_index]
    return sum(window, Decimal("0")) / Decimal(period)


@dataclass(slots=True)
class SymmetricSpyVwapPullbackStrategy(SpyVwapPullbackStrategy):
    """Long and short SPY VWAP pullback candidate for trend-continuation research."""

    name: ClassVar[str] = "spy-vwap-pullback-long-short"
    allow_short: ClassVar[bool] = True


@dataclass(slots=True)
class SpyVwapTrendContinuationLongShortBaseStrategy(SpyVwapPullbackStrategy):
    """Clean long/short VWAP trend-continuation baseline.

    This strategy starts the second VWAP research cycle from the directional
    thesis itself instead of inheriting the previous filter stack. It uses only
    completed regular-session bars, supports both sides symmetrically, and keeps
    volatility-normalized VWAP proximity as a configurable base constant.
    """

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-base"
    allow_short: ClassVar[bool] = True

    max_trades_per_day: int = 1
    first_entry_time: time = time(10, 0)
    last_entry_time: time = time(14, 30)
    # The runner fills market intents on the next bar open. Emitting the
    # flatten decision on the 15:50 bar lets a 5-minute backtest fill at 15:55
    # instead of carrying the position to the next session open.
    flatten_from: time = time(15, 50)
    vwap_near_tolerance_atr: Decimal = Decimal("0.25")
    atr_period_5m: int = 20

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Return side-aware entry decisions without hiding missing ATR context."""
        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"
        if self._current_atr_5m(state) is None:
            return DecisionAction.HOLD, "base_atr_not_ready"
        return SpyVwapPullbackStrategy._flat_position_decision(self, state=state, bar=bar)

    def _long_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Request a long after bullish VWAP pullback/reclaim confirmation."""
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        previous_vwap = _required_decimal(state.previous_vwap, "previous_vwap")
        opening_range_high = _required_decimal(
            state.first_30_minute_high,
            "first_30_minute_high",
        )
        previous_bar = _required_bar(state.previous_bar)
        atr_5m = self._current_atr_5m(state)
        if atr_5m is None:
            return DecisionAction.HOLD, "base_atr_not_ready"

        current_low = Decimal(str(bar.low))
        current_close = Decimal(str(bar.close))
        previous_close = Decimal(str(previous_bar.close))
        near_vwap_limit = current_vwap + self.vwap_near_tolerance_atr * atr_5m

        if (
            current_close > current_vwap
            and current_vwap > previous_vwap
            and current_close > opening_range_high
            and current_low <= near_vwap_limit
            and current_close > previous_close
        ):
            state.trades_entered += 1
            state.signal_bar_low = current_low
            state.signal_bar_high = Decimal(str(bar.high))
            state.signal_bar_vwap = current_vwap
            state.signal_bar_atr_5m = atr_5m
            state.initial_stop = None
            state.initial_risk = None
            state.initial_target = None
            state.open_trade_bars_held = 0
            state.max_open_r_since_entry = None
            return DecisionAction.ENTER_LONG, "long_vwap_trend_continuation_reclaim"

        return DecisionAction.HOLD, "long_base_entry_filter_not_met"

    def _short_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Request a short after bearish VWAP pullback/rejection confirmation."""
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        previous_vwap = _required_decimal(state.previous_vwap, "previous_vwap")
        opening_range_low = _required_decimal(
            state.first_30_minute_low,
            "first_30_minute_low",
        )
        previous_bar = _required_bar(state.previous_bar)
        atr_5m = self._current_atr_5m(state)
        if atr_5m is None:
            return DecisionAction.HOLD, "base_atr_not_ready"

        current_high = Decimal(str(bar.high))
        current_close = Decimal(str(bar.close))
        previous_close = Decimal(str(previous_bar.close))
        near_vwap_limit = current_vwap - self.vwap_near_tolerance_atr * atr_5m

        if (
            current_close < current_vwap
            and current_vwap < previous_vwap
            and current_close < opening_range_low
            and current_high >= near_vwap_limit
            and current_close < previous_close
        ):
            state.trades_entered += 1
            state.signal_bar_low = Decimal(str(bar.low))
            state.signal_bar_high = current_high
            state.signal_bar_vwap = current_vwap
            state.signal_bar_atr_5m = atr_5m
            state.initial_stop = None
            state.initial_risk = None
            state.initial_target = None
            state.open_trade_bars_held = 0
            state.max_open_r_since_entry = None
            return DecisionAction.ENTER_SHORT, "short_vwap_trend_continuation_rejection"

        return DecisionAction.HOLD, "short_base_entry_filter_not_met"

    def _open_long_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Exit long baseline trades on VWAP loss, signal failure, or EOD."""
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()
        current_close = Decimal(str(bar.close))
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")

        if local_time >= self.flatten_from:
            return DecisionAction.EXIT_LONG, "end_of_day_flatten"
        if state.signal_bar_low is not None and current_close < state.signal_bar_low:
            return DecisionAction.EXIT_LONG, "close_below_signal_bar_low"
        if current_close < current_vwap:
            return DecisionAction.EXIT_LONG, "close_below_vwap"
        return DecisionAction.HOLD, "long_base_thesis_still_valid"

    def _open_short_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Exit short baseline trades on VWAP reclaim, signal failure, or EOD."""
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()
        current_close = Decimal(str(bar.close))
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")

        if local_time >= self.flatten_from:
            return DecisionAction.EXIT_SHORT, "end_of_day_flatten"
        if state.signal_bar_high is not None and current_close > state.signal_bar_high:
            return DecisionAction.EXIT_SHORT, "close_above_signal_bar_high"
        if current_close > current_vwap:
            return DecisionAction.EXIT_SHORT, "close_above_vwap"
        return DecisionAction.HOLD, "short_base_thesis_still_valid"

    def _has_entry_context(self, *, state: _SessionState, bar: Bar) -> bool:
        """Return whether the clean baseline can consider a new entry."""
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()
        if local_time < self.first_entry_time:
            return False
        if local_time > self.last_entry_time:
            return False
        if state.trades_entered >= self.max_trades_per_day:
            return False
        if state.current_vwap is None or state.previous_vwap is None:
            return False
        if state.previous_bar is None:
            return False
        return state.first_30_minute_high is not None and state.first_30_minute_low is not None

    def _current_atr_5m(self, state: _SessionState) -> Decimal | None:
        """Return the current intraday 5-minute ATR if enough bars exist."""
        if len(state.true_ranges) < self.atr_period_5m:
            return None
        trailing_ranges = state.true_ranges[-self.atr_period_5m :]
        return sum(trailing_ranges, Decimal("0")) / Decimal(self.atr_period_5m)


@dataclass(slots=True)
class SpyVwapTrendContinuationDailyTrendFilterStrategy(
    SpyVwapTrendContinuationLongShortBaseStrategy
):
    """Clean long/short VWAP baseline gated by completed daily trend context."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-daily-trend-filter"

    daily_sma_period: int = 20
    daily_sma_slope_lookback_sessions: int = 5
    _completed_session_closes: list[Decimal] = field(
        default_factory=_new_decimal_list,
        init=False,
        repr=False,
    )

    def _state_for_bar(self, bar: Bar) -> _SessionState:
        """Record the prior regular-session close before the current day starts."""
        local_date = bar.timestamp_utc.astimezone(NEW_YORK).date().isoformat()
        if self._state is not None and self._state.local_date != local_date:
            previous_bar = self._state.previous_bar
            if previous_bar is not None:
                self._completed_session_closes.append(Decimal(str(previous_bar.close)))
        return SpyVwapTrendContinuationLongShortBaseStrategy._state_for_bar(self, bar)

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Route entries to the side supported by completed-daily context."""
        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"
        if self._current_atr_5m(state) is None:
            return DecisionAction.HOLD, "base_atr_not_ready"

        daily_trend_state = self._daily_trend_state()
        if daily_trend_state == "bullish_daily_context":
            return self._long_entry_decision(state=state, bar=bar)
        if daily_trend_state == "bearish_daily_context":
            return self._short_entry_decision(state=state, bar=bar)
        return DecisionAction.HOLD, daily_trend_state

    def _long_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Allow long entries only in bullish completed-daily context."""
        daily_trend_state = self._daily_trend_state()
        if daily_trend_state != "bullish_daily_context":
            return DecisionAction.HOLD, daily_trend_state
        return SpyVwapTrendContinuationLongShortBaseStrategy._long_entry_decision(
            self,
            state=state,
            bar=bar,
        )

    def _short_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Allow short entries only in bearish completed-daily context."""
        daily_trend_state = self._daily_trend_state()
        if daily_trend_state != "bearish_daily_context":
            return DecisionAction.HOLD, daily_trend_state
        return SpyVwapTrendContinuationLongShortBaseStrategy._short_entry_decision(
            self,
            state=state,
            bar=bar,
        )

    def _daily_trend_state(self) -> str:
        """Classify daily context using completed sessions only."""
        required_closes = self.daily_sma_period + self.daily_sma_slope_lookback_sessions
        if len(self._completed_session_closes) < required_closes:
            return "daily_context_not_ready"

        prior_regular_session_close = self._completed_session_closes[-1]
        daily_sma = _simple_moving_average(
            closes=self._completed_session_closes,
            period=self.daily_sma_period,
            end_offset=0,
        )
        daily_sma_lookback = _simple_moving_average(
            closes=self._completed_session_closes,
            period=self.daily_sma_period,
            end_offset=self.daily_sma_slope_lookback_sessions,
        )
        daily_sma_slope = daily_sma - daily_sma_lookback

        if prior_regular_session_close > daily_sma and daily_sma_slope >= 0:
            return "bullish_daily_context"
        if prior_regular_session_close < daily_sma and daily_sma_slope <= 0:
            return "bearish_daily_context"
        return "neutral_daily_context"


@dataclass(slots=True)
class SpyVwapTrendContinuationOpeningDriveFilterStrategy(
    SpyVwapTrendContinuationLongShortBaseStrategy
):
    """Clean long/short VWAP baseline gated by first-30-minute drive quality."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-opening-drive-filter"

    min_long_opening_close_location: Decimal = Decimal("0.60")
    max_short_opening_close_location: Decimal = Decimal("0.40")

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Route entries to the side supported by opening-drive quality."""
        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"
        if self._current_atr_5m(state) is None:
            return DecisionAction.HOLD, "base_atr_not_ready"

        opening_drive_state = self._opening_drive_state(state)
        if opening_drive_state == "bullish_opening_drive":
            return self._long_entry_decision(state=state, bar=bar)
        if opening_drive_state == "bearish_opening_drive":
            return self._short_entry_decision(state=state, bar=bar)
        return DecisionAction.HOLD, opening_drive_state

    def _opening_drive_state(self, state: _SessionState) -> str:
        """Classify first-30-minute directional quality for side-aware entries."""
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

        first_30_minute_return = (first_30_minute_close - session_open) / session_open
        if first_30_minute_high == first_30_minute_low:
            close_location = Decimal("0.50")
        else:
            close_location = (first_30_minute_close - first_30_minute_low) / (
                first_30_minute_high - first_30_minute_low
            )

        if first_30_minute_return >= 0 and close_location >= self.min_long_opening_close_location:
            return "bullish_opening_drive"
        if first_30_minute_return <= 0 and close_location <= self.max_short_opening_close_location:
            return "bearish_opening_drive"
        return "neutral_opening_drive"


@dataclass(slots=True)
class _SpyVwapTrendContinuationRvolFilterStrategy(SpyVwapTrendContinuationLongShortBaseStrategy):
    """Shared opening-RVOL gate for clean long/short VWAP baseline variants."""

    min_opening_rvol: Decimal | None = None
    max_opening_rvol: Decimal | None = None
    allow_missing_rvol: bool = False
    rvol_lookback_sessions: int = 20
    _opening_window_volumes: list[Decimal] = field(
        default_factory=_new_decimal_list,
        init=False,
        repr=False,
    )

    def _state_for_bar(self, bar: Bar) -> _SessionState:
        """Preserve completed opening-window volumes across session resets."""
        local_date = bar.timestamp_utc.astimezone(NEW_YORK).date().isoformat()
        if self._state is not None and self._state.local_date != local_date:
            self._record_completed_opening_window_volume(self._state)
        return SpyVwapTrendContinuationLongShortBaseStrategy._state_for_bar(self, bar)

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Apply the RVOL gate before evaluating the clean base setup."""
        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"
        if self._current_atr_5m(state) is None:
            return DecisionAction.HOLD, "base_atr_not_ready"

        rvol_gate_reason = self._rvol_gate_reason(state)
        if rvol_gate_reason is not None:
            return DecisionAction.HOLD, rvol_gate_reason
        return SpyVwapTrendContinuationLongShortBaseStrategy._flat_position_decision(
            self,
            state=state,
            bar=bar,
        )

    def _rvol_gate_reason(self, state: _SessionState) -> str | None:
        """Return a reject reason when opening RVOL is outside this variant."""
        opening_rvol = self._opening_relative_volume(state)
        if opening_rvol is None:
            return None if self.allow_missing_rvol else "opening_rvol_not_ready"
        if self.min_opening_rvol is not None and opening_rvol < self.min_opening_rvol:
            return "opening_rvol_too_low"
        if self.max_opening_rvol is not None and opening_rvol > self.max_opening_rvol:
            return "opening_rvol_too_high"
        return None

    def _opening_relative_volume(self, state: _SessionState) -> Decimal | None:
        """Compare today's completed opening volume with previous sessions only."""
        if len(self._opening_window_volumes) < self.rvol_lookback_sessions:
            return None
        trailing_window = self._opening_window_volumes[-self.rvol_lookback_sessions :]
        baseline = sum(trailing_window, Decimal("0")) / Decimal(len(trailing_window))
        if baseline == 0:
            return None
        return state.opening_window_volume / baseline

    def _record_completed_opening_window_volume(self, state: _SessionState) -> None:
        """Store one completed first-30-minute volume sample for future sessions."""
        if state.first_30_minute_close is None:
            return
        self._opening_window_volumes.append(state.opening_window_volume)


@dataclass(slots=True)
class SpyVwapTrendContinuationLooseRvolFilterStrategy(_SpyVwapTrendContinuationRvolFilterStrategy):
    """Clean long/short VWAP baseline with loose opening RVOL gate."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-rvol-loose-filter"

    min_opening_rvol: Decimal | None = Decimal("0.80")
    allow_missing_rvol: bool = True


@dataclass(slots=True)
class SpyVwapTrendContinuationActiveRvolFilterStrategy(_SpyVwapTrendContinuationRvolFilterStrategy):
    """Clean long/short VWAP baseline with active opening RVOL gate."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-rvol-active-filter"

    min_opening_rvol: Decimal | None = Decimal("1.20")


@dataclass(slots=True)
class SpyVwapTrendContinuationNormalToActiveRvolFilterStrategy(
    _SpyVwapTrendContinuationRvolFilterStrategy
):
    """Clean long/short VWAP baseline with normal-to-active opening RVOL gate."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-rvol-normal-active-filter"

    min_opening_rvol: Decimal | None = Decimal("0.80")
    max_opening_rvol: Decimal | None = Decimal("1.80")


@dataclass(slots=True)
class SpyVwapTrendContinuationAtrDistanceFilterStrategy(
    SpyVwapTrendContinuationLongShortBaseStrategy
):
    """Clean long/short VWAP baseline capped by close-to-VWAP ATR distance."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-atr-distance-filter"

    max_vwap_distance_atr_multiple: Decimal = Decimal("1.0")

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Preserve ATR-distance rejection reasons before trying another side."""
        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"
        if self._current_atr_5m(state) is None:
            return DecisionAction.HOLD, "base_atr_not_ready"

        long_action, long_reason = self._long_entry_decision(state=state, bar=bar)
        if long_action != DecisionAction.HOLD or long_reason == "atr_vwap_distance_too_extended":
            return long_action, long_reason
        short_action, short_reason = self._short_entry_decision(state=state, bar=bar)
        if short_action != DecisionAction.HOLD or short_reason == "atr_vwap_distance_too_extended":
            return short_action, short_reason
        return DecisionAction.HOLD, "pullback_entry_filter_not_met"

    def _long_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Reject long signals that close too far above VWAP."""
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        atr_5m = self._current_atr_5m(state)
        if atr_5m is None:
            return DecisionAction.HOLD, "base_atr_not_ready"
        current_close = Decimal(str(bar.close))
        if current_close > current_vwap + self.max_vwap_distance_atr_multiple * atr_5m:
            return DecisionAction.HOLD, "atr_vwap_distance_too_extended"
        return SpyVwapTrendContinuationLongShortBaseStrategy._long_entry_decision(
            self,
            state=state,
            bar=bar,
        )

    def _short_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Reject short signals that close too far below VWAP."""
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        atr_5m = self._current_atr_5m(state)
        if atr_5m is None:
            return DecisionAction.HOLD, "base_atr_not_ready"
        current_close = Decimal(str(bar.close))
        if current_close < current_vwap - self.max_vwap_distance_atr_multiple * atr_5m:
            return DecisionAction.HOLD, "atr_vwap_distance_too_extended"
        return SpyVwapTrendContinuationLongShortBaseStrategy._short_entry_decision(
            self,
            state=state,
            bar=bar,
        )


@dataclass(slots=True)
class _SpyVwapTrendContinuationOpeningRangeConfluenceFilterStrategy(
    SpyVwapTrendContinuationLongShortBaseStrategy
):
    """Shared side-aware VWAP/opening-range confluence gate."""

    max_vwap_opening_range_distance_atr_multiple: Decimal = Decimal("0.50")

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Preserve confluence rejection reasons before trying another side."""
        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"
        if self._current_atr_5m(state) is None:
            return DecisionAction.HOLD, "base_atr_not_ready"

        long_action, long_reason = self._long_entry_decision(state=state, bar=bar)
        if (
            long_action != DecisionAction.HOLD
            or long_reason == "vwap_opening_range_confluence_too_wide"
        ):
            return long_action, long_reason
        short_action, short_reason = self._short_entry_decision(state=state, bar=bar)
        if (
            short_action != DecisionAction.HOLD
            or short_reason == "vwap_opening_range_confluence_too_wide"
        ):
            return short_action, short_reason
        return DecisionAction.HOLD, "pullback_entry_filter_not_met"

    def _long_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Allow long signals only when VWAP is near opening-range high."""
        confluence_reason = self._confluence_reject_reason(state=state, side="long")
        if confluence_reason is not None:
            return DecisionAction.HOLD, confluence_reason
        return SpyVwapTrendContinuationLongShortBaseStrategy._long_entry_decision(
            self,
            state=state,
            bar=bar,
        )

    def _short_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Allow short signals only when VWAP is near opening-range low."""
        confluence_reason = self._confluence_reject_reason(state=state, side="short")
        if confluence_reason is not None:
            return DecisionAction.HOLD, confluence_reason
        return SpyVwapTrendContinuationLongShortBaseStrategy._short_entry_decision(
            self,
            state=state,
            bar=bar,
        )

    def _confluence_reject_reason(self, *, state: _SessionState, side: str) -> str | None:
        """Return a reject reason when VWAP is too far from the side's OR level."""
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        atr_5m = self._current_atr_5m(state)
        if atr_5m is None:
            return "base_atr_not_ready"
        opening_level = (
            _required_decimal(state.first_30_minute_high, "first_30_minute_high")
            if side == "long"
            else _required_decimal(state.first_30_minute_low, "first_30_minute_low")
        )
        distance_atr = abs(current_vwap - opening_level) / atr_5m
        if distance_atr > self.max_vwap_opening_range_distance_atr_multiple:
            return "vwap_opening_range_confluence_too_wide"
        return None


@dataclass(slots=True)
class SpyVwapTrendContinuationOpeningRangeConfluenceLooseFilterStrategy(
    _SpyVwapTrendContinuationOpeningRangeConfluenceFilterStrategy
):
    """Clean long/short VWAP baseline with VWAP/OR confluence within 1.00 ATR."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-vwap-or-confluence-1-00-filter"

    max_vwap_opening_range_distance_atr_multiple: Decimal = Decimal("1.00")


@dataclass(slots=True)
class SpyVwapTrendContinuationOpeningRangeConfluenceFilterStrategy(
    _SpyVwapTrendContinuationOpeningRangeConfluenceFilterStrategy
):
    """Clean long/short VWAP baseline with VWAP/OR confluence within 0.50 ATR."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-vwap-or-confluence-0-50-filter"


@dataclass(slots=True)
class SpyVwapTrendContinuationOpeningRangeConfluenceStrictFilterStrategy(
    _SpyVwapTrendContinuationOpeningRangeConfluenceFilterStrategy
):
    """Clean long/short VWAP baseline with VWAP/OR confluence within 0.25 ATR."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-vwap-or-confluence-0-25-filter"

    max_vwap_opening_range_distance_atr_multiple: Decimal = Decimal("0.25")


@dataclass(slots=True)
class _SpyVwapTrendContinuationRExitStrategy(SpyVwapTrendContinuationLongShortBaseStrategy):
    """Clean long/short VWAP baseline with initial-R stop and optional target."""

    minimum_realistic_risk: Decimal = Decimal("0.05")
    maximum_allowed_risk_atr_multiple: Decimal = Decimal("2.00")
    target_r_multiple: Decimal | None = None

    def decide(
        self,
        *,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> StrategyDecision:
        """Evaluate entries normally, then manage open trades with R exits."""
        state = self._state_for_bar(bar)
        self._update_vwap(state, bar)
        action = DecisionAction.HOLD
        reason = "waiting_for_setup"

        if state.bars_seen == 1:
            state.opening_range_high = Decimal(str(bar.high))
            state.opening_range_low = Decimal(str(bar.low))
            reason = "opening_range_seeded"
        elif context.position_quantity > 0:
            action, reason = self._open_long_r_decision(state=state, bar=bar, context=context)
        elif context.position_quantity < 0:
            action, reason = self._open_short_r_decision(state=state, bar=bar, context=context)
        else:
            action, reason = self._flat_position_decision(state=state, bar=bar)

        state.previous_bar = bar
        return self._decision(action=action, bar=bar, context=context, reason=reason)

    def _open_long_r_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> tuple[DecisionAction, str]:
        """Exit long trades on initial stop, optional target, or base exits."""
        invalid_reason = self._ensure_initial_risk(
            state=state,
            entry_price=context.average_entry_price,
            side="long",
        )
        if invalid_reason is not None:
            return DecisionAction.EXIT_LONG, f"{invalid_reason}@{context.average_entry_price}"

        stop = _required_decimal(state.initial_stop, "initial_stop")
        target = state.initial_target
        current_open = Decimal(str(bar.open))
        current_low = Decimal(str(bar.low))
        current_high = Decimal(str(bar.high))
        stop_hit = current_low <= stop
        target_hit = target is not None and current_high >= target
        if stop_hit and target_hit:
            if target is not None and current_open >= target:
                return DecisionAction.EXIT_LONG, f"r_target_exit@{target}"
            return DecisionAction.EXIT_LONG, f"r_initial_stop_exit@{stop}"
        if stop_hit:
            return DecisionAction.EXIT_LONG, f"r_initial_stop_exit@{stop}"
        if target_hit and target is not None:
            return DecisionAction.EXIT_LONG, f"r_target_exit@{target}"
        return SpyVwapTrendContinuationLongShortBaseStrategy._open_long_decision(
            self,
            state=state,
            bar=bar,
        )

    def _open_short_r_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> tuple[DecisionAction, str]:
        """Exit short trades on initial stop, optional target, or base exits."""
        invalid_reason = self._ensure_initial_risk(
            state=state,
            entry_price=context.average_entry_price,
            side="short",
        )
        if invalid_reason is not None:
            return DecisionAction.EXIT_SHORT, f"{invalid_reason}@{context.average_entry_price}"

        stop = _required_decimal(state.initial_stop, "initial_stop")
        target = state.initial_target
        current_open = Decimal(str(bar.open))
        current_low = Decimal(str(bar.low))
        current_high = Decimal(str(bar.high))
        stop_hit = current_high >= stop
        target_hit = target is not None and current_low <= target
        if stop_hit and target_hit:
            if target is not None and current_open <= target:
                return DecisionAction.EXIT_SHORT, f"r_target_exit@{target}"
            return DecisionAction.EXIT_SHORT, f"r_initial_stop_exit@{stop}"
        if stop_hit:
            return DecisionAction.EXIT_SHORT, f"r_initial_stop_exit@{stop}"
        if target_hit and target is not None:
            return DecisionAction.EXIT_SHORT, f"r_target_exit@{target}"
        return SpyVwapTrendContinuationLongShortBaseStrategy._open_short_decision(
            self,
            state=state,
            bar=bar,
        )

    def _ensure_initial_risk(
        self,
        *,
        state: _SessionState,
        entry_price: Decimal,
        side: str,
    ) -> str | None:
        """Calculate initial stop/risk/target once the runner has filled entry."""
        if state.initial_risk is not None:
            return None
        signal_vwap = _required_decimal(state.signal_bar_vwap, "signal_bar_vwap")
        signal_atr = _required_decimal(state.signal_bar_atr_5m, "signal_bar_atr_5m")
        if side == "long":
            signal_low = _required_decimal(state.signal_bar_low, "signal_bar_low")
            initial_stop = min(signal_low, signal_vwap - Decimal("0.25") * signal_atr)
            initial_risk = entry_price - initial_stop
            target = (
                entry_price + self.target_r_multiple * initial_risk
                if self.target_r_multiple is not None
                else None
            )
        else:
            signal_high = _required_decimal(state.signal_bar_high, "signal_bar_high")
            initial_stop = max(signal_high, signal_vwap + Decimal("0.25") * signal_atr)
            initial_risk = initial_stop - entry_price
            target = (
                entry_price - self.target_r_multiple * initial_risk
                if self.target_r_multiple is not None
                else None
            )
        state.initial_stop = initial_stop
        state.initial_risk = initial_risk
        state.initial_target = target
        if initial_risk <= 0:
            return "invalid_initial_risk_exit"
        if initial_risk < self.minimum_realistic_risk:
            return "initial_risk_too_small_exit"
        if initial_risk > self.maximum_allowed_risk_atr_multiple * signal_atr:
            return "initial_risk_too_large_exit"
        return None


@dataclass(slots=True)
class SpyVwapTrendContinuationInitialStopStrategy(_SpyVwapTrendContinuationRExitStrategy):
    """Clean long/short VWAP baseline with initial-R stop only."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-initial-stop"


@dataclass(slots=True)
class SpyVwapTrendContinuationOneRTargetStrategy(_SpyVwapTrendContinuationRExitStrategy):
    """Clean long/short VWAP baseline with initial stop and 1.0R target."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-1-0r-target"
    target_r_multiple: Decimal | None = Decimal("1.0")


@dataclass(slots=True)
class SpyVwapTrendContinuationOneAndHalfRTargetStrategy(_SpyVwapTrendContinuationRExitStrategy):
    """Clean long/short VWAP baseline with initial stop and 1.5R target."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-1-5r-target"
    target_r_multiple: Decimal | None = Decimal("1.5")


@dataclass(slots=True)
class SpyVwapTrendContinuationTwoRTargetStrategy(_SpyVwapTrendContinuationRExitStrategy):
    """Clean long/short VWAP baseline with initial stop and 2.0R target."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-2-0r-target"
    target_r_multiple: Decimal | None = Decimal("2.0")


class _SpyVwapTrendContinuationTimeStopMixin:
    """Shared time-stop logic based on open R progress since entry fill."""

    time_stop_bars: int = 4
    required_progress_r: Decimal = Decimal("0.30")
    minimum_realistic_risk: Decimal = Decimal("0.05")
    maximum_allowed_risk_atr_multiple: Decimal = Decimal("2.00")
    target_r_multiple: Decimal | None = None

    def _long_time_stop_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> tuple[DecisionAction, str] | None:
        """Exit a long trade that has not made enough open R progress."""
        invalid_reason = self._ensure_time_stop_risk(
            state=state,
            entry_price=context.average_entry_price,
            side="long",
        )
        if invalid_reason is not None:
            return DecisionAction.EXIT_LONG, f"{invalid_reason}@{context.average_entry_price}"

        state.open_trade_bars_held += 1
        current_close = Decimal(str(bar.close))
        initial_risk = _required_decimal(state.initial_risk, "initial_risk")
        open_r_progress = (current_close - context.average_entry_price) / initial_risk
        self._record_open_r_progress(state=state, open_r_progress=open_r_progress)
        if self._time_stop_triggered(state):
            return DecisionAction.EXIT_LONG, f"time_stop_stalled_exit@{current_close}"
        return None

    def _short_time_stop_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> tuple[DecisionAction, str] | None:
        """Exit a short trade that has not made enough open R progress."""
        invalid_reason = self._ensure_time_stop_risk(
            state=state,
            entry_price=context.average_entry_price,
            side="short",
        )
        if invalid_reason is not None:
            return DecisionAction.EXIT_SHORT, f"{invalid_reason}@{context.average_entry_price}"

        state.open_trade_bars_held += 1
        current_close = Decimal(str(bar.close))
        initial_risk = _required_decimal(state.initial_risk, "initial_risk")
        open_r_progress = (context.average_entry_price - current_close) / initial_risk
        self._record_open_r_progress(state=state, open_r_progress=open_r_progress)
        if self._time_stop_triggered(state):
            return DecisionAction.EXIT_SHORT, f"time_stop_stalled_exit@{current_close}"
        return None

    def _ensure_time_stop_risk(
        self,
        *,
        state: _SessionState,
        entry_price: Decimal,
        side: str,
    ) -> str | None:
        """Calculate the initial R denominator once after the runner fills entry."""
        if state.initial_risk is not None:
            return None
        signal_vwap = _required_decimal(state.signal_bar_vwap, "signal_bar_vwap")
        signal_atr = _required_decimal(state.signal_bar_atr_5m, "signal_bar_atr_5m")
        if side == "long":
            signal_low = _required_decimal(state.signal_bar_low, "signal_bar_low")
            initial_stop = min(signal_low, signal_vwap - Decimal("0.25") * signal_atr)
            initial_risk = entry_price - initial_stop
            target = (
                entry_price + self.target_r_multiple * initial_risk
                if self.target_r_multiple is not None
                else None
            )
        else:
            signal_high = _required_decimal(state.signal_bar_high, "signal_bar_high")
            initial_stop = max(signal_high, signal_vwap + Decimal("0.25") * signal_atr)
            initial_risk = initial_stop - entry_price
            target = (
                entry_price - self.target_r_multiple * initial_risk
                if self.target_r_multiple is not None
                else None
            )

        state.initial_stop = initial_stop
        state.initial_risk = initial_risk
        state.initial_target = target
        state.open_trade_bars_held = 0
        state.max_open_r_since_entry = None
        if initial_risk <= 0:
            return "invalid_initial_risk_exit"
        if initial_risk < self.minimum_realistic_risk:
            return "initial_risk_too_small_exit"
        if initial_risk > self.maximum_allowed_risk_atr_multiple * signal_atr:
            return "initial_risk_too_large_exit"
        return None

    def _record_open_r_progress(
        self,
        *,
        state: _SessionState,
        open_r_progress: Decimal,
    ) -> None:
        """Track the best open R progress observed on completed bars."""
        state.max_open_r_since_entry = (
            open_r_progress
            if state.max_open_r_since_entry is None
            else max(state.max_open_r_since_entry, open_r_progress)
        )

    def _time_stop_triggered(self, state: _SessionState) -> bool:
        """Return whether this open trade has stalled past the time-stop threshold."""
        if state.open_trade_bars_held < self.time_stop_bars:
            return False
        max_open_r = _required_decimal(state.max_open_r_since_entry, "max_open_r_since_entry")
        return max_open_r < self.required_progress_r


@dataclass(slots=True)
class SpyVwapTrendContinuationTimeStopStrategy(
    _SpyVwapTrendContinuationTimeStopMixin,
    SpyVwapTrendContinuationLongShortBaseStrategy,
):
    """Clean long/short VWAP baseline with stalled-trade time stop."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-time-stop-4-030r"
    time_stop_bars: int = 4
    required_progress_r: Decimal = Decimal("0.30")
    minimum_realistic_risk: Decimal = Decimal("0.05")
    maximum_allowed_risk_atr_multiple: Decimal = Decimal("2.00")
    target_r_multiple: Decimal | None = None

    def _open_long_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        context: StrategyDecisionContext | None = None,
    ) -> tuple[DecisionAction, str]:
        """Apply the time stop before baseline long exits."""
        if context is None:
            return SpyVwapTrendContinuationLongShortBaseStrategy._open_long_decision(
                self,
                state=state,
                bar=bar,
            )
        time_stop_decision = self._long_time_stop_decision(state=state, bar=bar, context=context)
        if time_stop_decision is not None:
            return time_stop_decision
        return SpyVwapTrendContinuationLongShortBaseStrategy._open_long_decision(
            self,
            state=state,
            bar=bar,
        )

    def _open_short_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        context: StrategyDecisionContext | None = None,
    ) -> tuple[DecisionAction, str]:
        """Apply the time stop before baseline short exits."""
        if context is None:
            return SpyVwapTrendContinuationLongShortBaseStrategy._open_short_decision(
                self,
                state=state,
                bar=bar,
            )
        time_stop_decision = self._short_time_stop_decision(state=state, bar=bar, context=context)
        if time_stop_decision is not None:
            return time_stop_decision
        return SpyVwapTrendContinuationLongShortBaseStrategy._open_short_decision(
            self,
            state=state,
            bar=bar,
        )

    def decide(
        self,
        *,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> StrategyDecision:
        """Evaluate baseline entries and manage open trades with a time stop."""
        state = self._state_for_bar(bar)
        self._update_vwap(state, bar)
        action = DecisionAction.HOLD
        reason = "waiting_for_setup"

        if state.bars_seen == 1:
            state.opening_range_high = Decimal(str(bar.high))
            state.opening_range_low = Decimal(str(bar.low))
            reason = "opening_range_seeded"
        elif context.position_quantity > 0:
            action, reason = self._open_long_decision(state=state, bar=bar, context=context)
        elif context.position_quantity < 0:
            action, reason = self._open_short_decision(state=state, bar=bar, context=context)
        else:
            action, reason = self._flat_position_decision(state=state, bar=bar)

        state.previous_bar = bar
        return self._decision(action=action, bar=bar, context=context, reason=reason)


@dataclass(slots=True)
class SpyVwapTrendContinuationTimeStopThreeBarStrategy(SpyVwapTrendContinuationTimeStopStrategy):
    """Clean long/short VWAP baseline with 3-bar stalled-trade time stop."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-time-stop-3-030r"
    time_stop_bars: int = 3


@dataclass(slots=True)
class SpyVwapTrendContinuationTimeStopSixBarStrategy(SpyVwapTrendContinuationTimeStopStrategy):
    """Clean long/short VWAP baseline with 6-bar stalled-trade time stop."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-time-stop-6-030r"
    time_stop_bars: int = 6


@dataclass(slots=True)
class SpyVwapTrendContinuationOneRTargetTimeStopStrategy(
    _SpyVwapTrendContinuationTimeStopMixin,
    SpyVwapTrendContinuationOneRTargetStrategy,
):
    """Clean long/short VWAP baseline with 1.0R target plus stalled-trade time stop."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-1-0r-target-time-stop"
    time_stop_bars: int = 4
    required_progress_r: Decimal = Decimal("0.30")

    def _open_long_r_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> tuple[DecisionAction, str]:
        """Apply time stop before R stop/target long exits."""
        time_stop_decision = self._long_time_stop_decision(state=state, bar=bar, context=context)
        if time_stop_decision is not None:
            return time_stop_decision
        return SpyVwapTrendContinuationOneRTargetStrategy._open_long_r_decision(
            self,
            state=state,
            bar=bar,
            context=context,
        )

    def _open_short_r_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> tuple[DecisionAction, str]:
        """Apply time stop before R stop/target short exits."""
        time_stop_decision = self._short_time_stop_decision(state=state, bar=bar, context=context)
        if time_stop_decision is not None:
            return time_stop_decision
        return SpyVwapTrendContinuationOneRTargetStrategy._open_short_r_decision(
            self,
            state=state,
            bar=bar,
            context=context,
        )


@dataclass(slots=True)
class _SpyVwapTrendContinuationSignalQualityFilterStrategy(
    SpyVwapTrendContinuationLongShortBaseStrategy
):
    """Shared signal-bar quality gate for clean long/short VWAP baseline variants."""

    min_long_close_location: Decimal = Decimal("0.50")
    max_short_close_location: Decimal = Decimal("0.50")
    min_body_pct_of_range: Decimal | None = None

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Preserve signal-quality rejection reasons before trying another side."""
        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"
        if self._current_atr_5m(state) is None:
            return DecisionAction.HOLD, "base_atr_not_ready"

        long_action, long_reason = self._long_entry_decision(state=state, bar=bar)
        if long_action != DecisionAction.HOLD or long_reason.startswith("signal_bar_"):
            return long_action, long_reason
        short_action, short_reason = self._short_entry_decision(state=state, bar=bar)
        if short_action != DecisionAction.HOLD or short_reason.startswith("signal_bar_"):
            return short_action, short_reason
        return DecisionAction.HOLD, "pullback_entry_filter_not_met"

    def _long_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Require bullish signal-bar quality before long base entry."""
        quality_reason = self._signal_quality_reason(bar=bar, side="long")
        if quality_reason is not None:
            return DecisionAction.HOLD, quality_reason
        return SpyVwapTrendContinuationLongShortBaseStrategy._long_entry_decision(
            self,
            state=state,
            bar=bar,
        )

    def _short_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Require bearish signal-bar quality before short base entry."""
        quality_reason = self._signal_quality_reason(bar=bar, side="short")
        if quality_reason is not None:
            return DecisionAction.HOLD, quality_reason
        return SpyVwapTrendContinuationLongShortBaseStrategy._short_entry_decision(
            self,
            state=state,
            bar=bar,
        )

    def _signal_quality_reason(self, *, bar: Bar, side: str) -> str | None:
        """Return a reject reason when signal-bar shape is too weak."""
        low = Decimal(str(bar.low))
        high = Decimal(str(bar.high))
        signal_range = high - low
        if signal_range == 0:
            close_location = Decimal("0.50")
            body_pct_of_range = Decimal("0")
        else:
            close = Decimal(str(bar.close))
            open_price = Decimal(str(bar.open))
            close_location = (close - low) / signal_range
            body_pct_of_range = abs(close - open_price) / signal_range

        if side == "long" and close_location < self.min_long_close_location:
            return "signal_bar_close_location_too_weak"
        if side == "short" and close_location > self.max_short_close_location:
            return "signal_bar_close_location_too_weak"
        if (
            self.min_body_pct_of_range is not None
            and body_pct_of_range < self.min_body_pct_of_range
        ):
            return "signal_bar_body_too_small"
        return None


@dataclass(slots=True)
class SpyVwapTrendContinuationBasicSignalQualityFilterStrategy(
    _SpyVwapTrendContinuationSignalQualityFilterStrategy
):
    """Clean long/short VWAP baseline with basic signal-bar close-location gate."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-signal-quality-basic-filter"


@dataclass(slots=True)
class SpyVwapTrendContinuationStrongSignalQualityFilterStrategy(
    _SpyVwapTrendContinuationSignalQualityFilterStrategy
):
    """Clean long/short VWAP baseline with stronger signal-bar quality gate."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-signal-quality-strong-filter"

    min_long_close_location: Decimal = Decimal("0.60")
    max_short_close_location: Decimal = Decimal("0.40")
    min_body_pct_of_range: Decimal | None = Decimal("0.30")


@dataclass(slots=True)
class _SpyVwapTrendContinuationSignalBreakEntryStrategy(
    SpyVwapTrendContinuationLongShortBaseStrategy
):
    """Delay entry until the next bar confirms beyond the signal-bar extreme."""

    signal_valid_bars: int = 1

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Store fresh signals, then fill only after next-bar break confirmation."""
        pending_action, pending_reason = self._pending_break_entry_decision(
            state=state,
            bar=bar,
        )
        if (
            pending_action != DecisionAction.HOLD
            or state.pending_break_side is not None
            or pending_reason != "no_pending_signal_bar_break"
        ):
            return pending_action, pending_reason

        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"
        if self._current_atr_5m(state) is None:
            return DecisionAction.HOLD, "base_atr_not_ready"

        long_action, long_reason = self._long_signal_decision(state=state, bar=bar)
        if long_action == DecisionAction.ENTER_LONG:
            self._store_pending_break_signal(state=state, side="long")
            return DecisionAction.HOLD, "long_signal_bar_break_pending"
        if long_reason.startswith("signal_bar_"):
            return DecisionAction.HOLD, long_reason

        short_action, short_reason = self._short_signal_decision(state=state, bar=bar)
        if short_action == DecisionAction.ENTER_SHORT:
            self._store_pending_break_signal(state=state, side="short")
            return DecisionAction.HOLD, "short_signal_bar_break_pending"
        if short_reason.startswith("signal_bar_"):
            return DecisionAction.HOLD, short_reason

        return DecisionAction.HOLD, "pullback_entry_filter_not_met"

    def _long_signal_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Evaluate the long setup that must be confirmed by a later break."""
        return SpyVwapTrendContinuationLongShortBaseStrategy._long_entry_decision(
            self,
            state=state,
            bar=bar,
        )

    def _short_signal_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Evaluate the short setup that must be confirmed by a later break."""
        return SpyVwapTrendContinuationLongShortBaseStrategy._short_entry_decision(
            self,
            state=state,
            bar=bar,
        )

    def _store_pending_break_signal(self, *, state: _SessionState, side: str) -> None:
        """Save the signal-bar extreme and undo the base strategy's trade count."""
        if state.trades_entered > 0:
            state.trades_entered -= 1
        state.pending_break_side = side
        state.pending_break_signal_low = state.signal_bar_low
        state.pending_break_signal_high = state.signal_bar_high
        state.pending_break_bars_remaining = max(self.signal_valid_bars, 1)

    def _pending_break_entry_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Enter on a confirmed signal-bar break or expire the pending signal."""
        if state.pending_break_side is None:
            return DecisionAction.HOLD, "no_pending_signal_bar_break"

        signal_low = _required_decimal(
            state.pending_break_signal_low,
            "pending_break_signal_low",
        )
        signal_high = _required_decimal(
            state.pending_break_signal_high,
            "pending_break_signal_high",
        )
        current_open = Decimal(str(bar.open))
        current_high = Decimal(str(bar.high))
        current_low = Decimal(str(bar.low))

        if state.pending_break_side == "long" and current_high > signal_high:
            entry_reference_price = max(current_open, signal_high)
            self._clear_pending_break_signal(state)
            state.trades_entered += 1
            return (
                DecisionAction.ENTER_LONG,
                f"long_signal_bar_break_entry@{entry_reference_price}",
            )

        if state.pending_break_side == "short" and current_low < signal_low:
            entry_reference_price = min(current_open, signal_low)
            self._clear_pending_break_signal(state)
            state.trades_entered += 1
            return (
                DecisionAction.ENTER_SHORT,
                f"short_signal_bar_break_entry@{entry_reference_price}",
            )

        state.pending_break_bars_remaining -= 1
        if state.pending_break_bars_remaining <= 0:
            self._clear_pending_break_signal(state)
            return DecisionAction.HOLD, "signal_bar_break_expired"
        return DecisionAction.HOLD, "signal_bar_break_not_confirmed"

    def _clear_pending_break_signal(self, state: _SessionState) -> None:
        """Clear pending break-entry state after fill or expiry."""
        state.pending_break_side = None
        state.pending_break_signal_low = None
        state.pending_break_signal_high = None
        state.pending_break_bars_remaining = 0


@dataclass(slots=True)
class SpyVwapTrendContinuationSignalBreakEntryStrategy(
    _SpyVwapTrendContinuationSignalBreakEntryStrategy
):
    """Clean long/short VWAP baseline with signal-bar break confirmation entry."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-signal-break-entry"


@dataclass(slots=True)
class SpyVwapTrendContinuationSignalQualityBreakEntryStrategy(
    _SpyVwapTrendContinuationSignalBreakEntryStrategy
):
    """Clean long/short VWAP baseline with basic signal quality plus break entry."""

    name: ClassVar[str] = "spy-vwap-trend-continuation-long-short-signal-quality-break-entry"

    min_long_close_location: Decimal = Decimal("0.50")
    max_short_close_location: Decimal = Decimal("0.50")
    min_body_pct_of_range: Decimal | None = None

    def _long_signal_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Require basic bullish signal-bar quality before pending break confirmation."""
        quality_reason = self._signal_quality_reason(bar=bar, side="long")
        if quality_reason is not None:
            return DecisionAction.HOLD, quality_reason
        return _SpyVwapTrendContinuationSignalBreakEntryStrategy._long_signal_decision(
            self,
            state=state,
            bar=bar,
        )

    def _short_signal_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Require basic bearish signal-bar quality before pending break confirmation."""
        quality_reason = self._signal_quality_reason(bar=bar, side="short")
        if quality_reason is not None:
            return DecisionAction.HOLD, quality_reason
        return _SpyVwapTrendContinuationSignalBreakEntryStrategy._short_signal_decision(
            self,
            state=state,
            bar=bar,
        )

    def _signal_quality_reason(self, *, bar: Bar, side: str) -> str | None:
        """Return a reject reason when signal-bar shape is too weak."""
        low = Decimal(str(bar.low))
        high = Decimal(str(bar.high))
        signal_range = high - low
        if signal_range == 0:
            close_location = Decimal("0.50")
            body_pct_of_range = Decimal("0")
        else:
            close = Decimal(str(bar.close))
            open_price = Decimal(str(bar.open))
            close_location = (close - low) / signal_range
            body_pct_of_range = abs(close - open_price) / signal_range

        if side == "long" and close_location < self.min_long_close_location:
            return "signal_bar_close_location_too_weak"
        if side == "short" and close_location > self.max_short_close_location:
            return "signal_bar_close_location_too_weak"
        if (
            self.min_body_pct_of_range is not None
            and body_pct_of_range < self.min_body_pct_of_range
        ):
            return "signal_bar_body_too_small"
        return None


@dataclass(slots=True)
class SpyVwapRangeReversionStrategy(SpyVwapTrendContinuationLongShortBaseStrategy):
    """Separate VWAP range-day mean-reversion playbook."""

    name: ClassVar[str] = "spy-vwap-range-reversion-base"

    max_trades_per_day: int = 2
    vwap_band_atr_multiple: Decimal = Decimal("1.0")
    max_opening_range_pct: Decimal = Decimal("0.0120")
    max_vwap_slope_atr_multiple: Decimal = Decimal("0.10")
    min_vwap_crosses: int = 2
    stop_atr_multiple: Decimal = Decimal("1.0")
    _previous_session_high: Decimal | None = field(default=None, init=False, repr=False)
    _previous_session_low: Decimal | None = field(default=None, init=False, repr=False)

    def decide(
        self,
        *,
        bar: Bar,
        context: StrategyDecisionContext,
    ) -> StrategyDecision:
        """Evaluate one bar while deriving range-reversion risk from the filled entry.

        The runner fills entry intents on the next bar open, so this variant
        re-validates its stop against the actual simulated fill price before
        applying intrabar target/stop handling.
        """
        state = self._state_for_bar(bar)
        self._update_vwap(state, bar)
        action = DecisionAction.HOLD
        reason = "waiting_for_setup"

        if state.bars_seen == 1:
            state.opening_range_high = Decimal(str(bar.high))
            state.opening_range_low = Decimal(str(bar.low))
            reason = "opening_range_seeded"
        elif context.position_quantity > 0:
            invalid_reason = self._ensure_range_reversion_initial_risk(
                state=state,
                entry_price=context.average_entry_price,
                side="long",
            )
            if invalid_reason is not None:
                action, reason = DecisionAction.EXIT_LONG, invalid_reason
            else:
                action, reason = self._open_long_decision(state=state, bar=bar)
        elif context.position_quantity < 0:
            invalid_reason = self._ensure_range_reversion_initial_risk(
                state=state,
                entry_price=context.average_entry_price,
                side="short",
            )
            if invalid_reason is not None:
                action, reason = DecisionAction.EXIT_SHORT, invalid_reason
            else:
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
        """Carry prior-session range into the next session without lookahead."""
        local_date = bar.timestamp_utc.astimezone(NEW_YORK).date().isoformat()
        if self._state is not None and self._state.local_date != local_date:
            self._previous_session_high = self._state.session_high
            self._previous_session_low = self._state.session_low
        return SpyVwapTrendContinuationLongShortBaseStrategy._state_for_bar(self, bar)

    def _flat_position_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Enter only when range-day context and VWAP distance agree."""
        if not self._has_entry_context(state=state, bar=bar):
            return DecisionAction.HOLD, "entry_context_not_ready"
        if self._current_atr_5m(state) is None:
            return DecisionAction.HOLD, "base_atr_not_ready"
        range_reason = self._range_candidate_reject_reason(state=state, bar=bar)
        if range_reason is not None:
            return DecisionAction.HOLD, range_reason

        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        atr_5m = _required_decimal(self._current_atr_5m(state), "atr_5m")
        current_close = Decimal(str(bar.close))
        previous_close = Decimal(str(_required_bar(state.previous_bar).close))
        if current_close <= current_vwap - self.vwap_band_atr_multiple * atr_5m:
            if current_close > previous_close:
                target, stop = self._range_reversion_levels(
                    entry_price=current_close,
                    current_vwap=current_vwap,
                    atr_5m=atr_5m,
                    side="long",
                )
                invalid_reason = self._invalid_range_reversion_stop_reason(
                    entry_price=current_close,
                    stop=stop,
                    side="long",
                )
                if invalid_reason is not None:
                    return DecisionAction.HOLD, invalid_reason
                state.trades_entered += 1
                state.signal_bar_vwap = current_vwap
                state.signal_bar_atr_5m = atr_5m
                state.initial_target = target
                state.initial_stop = stop
                state.initial_risk = None
                return DecisionAction.ENTER_LONG, "range_reversion_long_turn_up"
            return DecisionAction.HOLD, "range_reversion_long_turn_not_confirmed"
        if current_close >= current_vwap + self.vwap_band_atr_multiple * atr_5m:
            if current_close < previous_close:
                target, stop = self._range_reversion_levels(
                    entry_price=current_close,
                    current_vwap=current_vwap,
                    atr_5m=atr_5m,
                    side="short",
                )
                invalid_reason = self._invalid_range_reversion_stop_reason(
                    entry_price=current_close,
                    stop=stop,
                    side="short",
                )
                if invalid_reason is not None:
                    return DecisionAction.HOLD, invalid_reason
                state.trades_entered += 1
                state.signal_bar_vwap = current_vwap
                state.signal_bar_atr_5m = atr_5m
                state.initial_target = target
                state.initial_stop = stop
                state.initial_risk = None
                return DecisionAction.ENTER_SHORT, "range_reversion_short_turn_down"
            return DecisionAction.HOLD, "range_reversion_short_turn_not_confirmed"
        return DecisionAction.HOLD, "range_reversion_vwap_band_not_reached"

    def _open_long_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Exit long range-reversion trades at VWAP target, stop, or EOD."""
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()
        target = _required_decimal(state.initial_target, "initial_target")
        stop = _required_decimal(state.initial_stop, "initial_stop")
        current_open = Decimal(str(bar.open))
        current_high = Decimal(str(bar.high))
        current_low = Decimal(str(bar.low))
        if local_time >= self.flatten_from:
            return DecisionAction.EXIT_LONG, "end_of_day_flatten"
        if current_low <= stop and current_high >= target:
            if current_open >= target:
                return DecisionAction.EXIT_LONG, f"range_reversion_target_exit@{target}"
            return DecisionAction.EXIT_LONG, f"range_reversion_stop_exit@{stop}"
        if current_low <= stop:
            return DecisionAction.EXIT_LONG, f"range_reversion_stop_exit@{stop}"
        if current_high >= target:
            return DecisionAction.EXIT_LONG, f"range_reversion_target_exit@{target}"
        return DecisionAction.HOLD, "range_reversion_long_still_open"

    def _open_short_decision(
        self,
        *,
        state: _SessionState,
        bar: Bar,
    ) -> tuple[DecisionAction, str]:
        """Exit short range-reversion trades at VWAP target, stop, or EOD."""
        local_time = bar.timestamp_utc.astimezone(NEW_YORK).time()
        target = _required_decimal(state.initial_target, "initial_target")
        stop = _required_decimal(state.initial_stop, "initial_stop")
        current_open = Decimal(str(bar.open))
        current_high = Decimal(str(bar.high))
        current_low = Decimal(str(bar.low))
        if local_time >= self.flatten_from:
            return DecisionAction.EXIT_SHORT, "end_of_day_flatten"
        if current_high >= stop and current_low <= target:
            if current_open <= target:
                return DecisionAction.EXIT_SHORT, f"range_reversion_target_exit@{target}"
            return DecisionAction.EXIT_SHORT, f"range_reversion_stop_exit@{stop}"
        if current_high >= stop:
            return DecisionAction.EXIT_SHORT, f"range_reversion_stop_exit@{stop}"
        if current_low <= target:
            return DecisionAction.EXIT_SHORT, f"range_reversion_target_exit@{target}"
        return DecisionAction.HOLD, "range_reversion_short_still_open"

    def _range_candidate_reject_reason(self, *, state: _SessionState, bar: Bar) -> str | None:
        """Return why the current context is not range-like enough."""
        if self._previous_session_high is None or self._previous_session_low is None:
            return "prior_session_range_not_ready"
        session_open = _required_decimal(state.session_open, "session_open")
        opening_high = _required_decimal(state.first_30_minute_high, "first_30_minute_high")
        opening_low = _required_decimal(state.first_30_minute_low, "first_30_minute_low")
        if session_open == 0:
            return "range_reversion_session_open_invalid"
        opening_range_pct = (opening_high - opening_low) / session_open
        if opening_range_pct > self.max_opening_range_pct:
            return "range_reversion_opening_range_too_wide"
        current_close = Decimal(str(bar.close))
        if not self._previous_session_low <= current_close <= self._previous_session_high:
            return "range_reversion_outside_prior_session_range"

        atr_5m = _required_decimal(self._current_atr_5m(state), "atr_5m")
        current_vwap = _required_decimal(state.current_vwap, "current_vwap")
        previous_bars = self._session_bars_from_state(state)
        previous_vwap = self._range_vwap(previous_bars[:-3]) if len(previous_bars) > 3 else None
        if previous_vwap is None or abs(current_vwap - previous_vwap) > (
            self.max_vwap_slope_atr_multiple * atr_5m
        ):
            return "range_reversion_vwap_slope_too_steep"
        if self._vwap_cross_count(previous_bars) < self.min_vwap_crosses:
            return "range_reversion_not_enough_vwap_crosses"
        return None

    def _ensure_range_reversion_initial_risk(
        self,
        *,
        state: _SessionState,
        entry_price: Decimal,
        side: str,
    ) -> str | None:
        """Bind the stop to the actual filled entry price exactly once."""
        if state.initial_risk is not None:
            return None
        signal_vwap = _required_decimal(state.signal_bar_vwap, "signal_bar_vwap")
        signal_atr = _required_decimal(state.signal_bar_atr_5m, "signal_bar_atr_5m")
        target, stop = self._range_reversion_levels(
            entry_price=entry_price,
            current_vwap=signal_vwap,
            atr_5m=signal_atr,
            side=side,
        )
        invalid_reason = self._invalid_range_reversion_stop_reason(
            entry_price=entry_price,
            stop=stop,
            side=side,
        )
        if invalid_reason is not None:
            return invalid_reason
        state.initial_target = target
        state.initial_stop = stop
        if side == "long":
            state.initial_risk = entry_price - stop
        else:
            state.initial_risk = stop - entry_price
        return None

    def _range_reversion_levels(
        self,
        *,
        entry_price: Decimal,
        current_vwap: Decimal,
        atr_5m: Decimal,
        side: str,
    ) -> tuple[Decimal, Decimal]:
        """Return the mean-reversion target and entry-relative protective stop."""
        target = current_vwap
        if side == "long":
            return target, entry_price - self.stop_atr_multiple * atr_5m
        return target, entry_price + self.stop_atr_multiple * atr_5m

    def _invalid_range_reversion_stop_reason(
        self,
        *,
        entry_price: Decimal,
        stop: Decimal,
        side: str,
    ) -> str | None:
        """Return a clear reason when the proposed stop is not protective."""
        if side == "long" and stop >= entry_price:
            return "invalid_long_stop_not_below_entry"
        if side == "short" and stop <= entry_price:
            return "invalid_short_stop_not_above_entry"
        return None

    def _session_bars_from_state(self, state: _SessionState) -> tuple[Bar, ...]:
        """Reconstruct completed bars needed by range diagnostics from state history.

        The strategy keeps only the previous bar in normal operation, so this method
        is intentionally overridden by a small state-local cache in this subclass.
        """
        return state.range_reversion_bars

    def _update_vwap(self, state: _SessionState, bar: Bar) -> None:
        """Update VWAP and retain completed bars for range diagnostics."""
        SpyVwapTrendContinuationLongShortBaseStrategy._update_vwap(self, state, bar)
        state.range_reversion_bars = (*state.range_reversion_bars, bar)

    def _vwap_cross_count(self, bars: Sequence[Bar]) -> int:
        """Count completed-bar close crossings around running session VWAP."""
        previous_side: int | None = None
        crosses = 0
        for index in range(1, len(bars) + 1):
            running_vwap = self._range_vwap(bars[:index])
            if running_vwap is None:
                continue
            close = Decimal(str(bars[index - 1].close))
            side = 1 if close > running_vwap else -1 if close < running_vwap else 0
            if side == 0:
                continue
            if previous_side is not None and side != previous_side:
                crosses += 1
            previous_side = side
        return crosses

    def _range_vwap(self, bars: Sequence[Bar]) -> Decimal | None:
        """Calculate VWAP for this playbook's local range diagnostics."""
        total_volume = sum((Decimal(bar.volume) for bar in bars), Decimal("0"))
        if total_volume == 0:
            return None
        total_price_volume = sum(
            (
                (Decimal(str(bar.high)) + Decimal(str(bar.low)) + Decimal(str(bar.close)))
                / Decimal("3")
            )
            * Decimal(bar.volume)
            for bar in bars
        )
        return total_price_volume / total_volume


@dataclass(slots=True)
class SpyVwapRangeReversionOneAtrBandStrategy(SpyVwapRangeReversionStrategy):
    """Range-reversion playbook requiring 1.0 ATR distance from VWAP."""

    name: ClassVar[str] = "spy-vwap-range-reversion-1-0atr-band"
    vwap_band_atr_multiple: Decimal = Decimal("1.0")


@dataclass(slots=True)
class SpyVwapRangeReversionOneAndHalfAtrBandStrategy(SpyVwapRangeReversionStrategy):
    """Range-reversion playbook requiring 1.5 ATR distance from VWAP."""

    name: ClassVar[str] = "spy-vwap-range-reversion-1-5atr-band"
    vwap_band_atr_multiple: Decimal = Decimal("1.5")


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
