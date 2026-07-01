"""Backtest engine: bar-by-bar loop driving one strategy.

The engine owns the run state (position, realized PnL, pending order intent,
per-trade diagnostics tracker). Everything else is delegated:

    - records       -> trade_research_app.backtest.records
    - fill accounting-> trade_research_app.backtest.fill_model
    - diagnostics   -> trade_research_app.backtest.diagnostics
    - enrichment    -> trade_research_app.backtest.enrichment
    - summary       -> trade_research_app.backtest.summary
    - cli wiring    -> trade_research_app.backtest.cli_wiring
    - analytics     -> trade_analytics.{metrics, breakdowns, session_regimes}

The single ``_handle_fill`` method replaces the two near-identical fill blocks
that previously handled pending next-open fills and explicit-reference-price
fills. Both paths produce one ``SimulatedFill`` and an exit-reason label; the
shared code simulates, applies, records the closed trade, and resets the
open-trade tracker.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trade_analytics.metrics import ClosedTrade
from trade_core import (
    DecisionAction,
    InstrumentRef,
    OrderIntent,
    OrderIntentId,
    OrderType,
    RiskDecision,
    RiskDecisionId,
    RiskOutcome,
    StrategyInputRef,
    StrategyRunId,
)
from trade_data import Bar, HistoricalBarsRequest, LocalMarketDataStore
from trade_data.sessions import get_market_session_config
from trade_strategies import Strategy, StrategyDecisionContext

from trade_research_app.backtest.cli_wiring import (
    bar_close_time,
    decision_rule_reason,
    explicit_decision_reference_price,
    strategy_run_id,
    strategy_variant_name,
)
from trade_research_app.backtest.diagnostics import TradeDiagnosticsTracker
from trade_research_app.backtest.enrichment import enrich_closed_trades
from trade_research_app.backtest.fill_model import (
    apply_fill,
    call_on_entry,
    closed_trade_pnl,
    is_opening_fill,
    order_side_for_action,
    required_order_side,
    risk_outcome_for_action,
    simulate_next_open_fill,
)
from trade_research_app.backtest.records import BacktestCostModel, BacktestSummary, SimulatedFill
from trade_research_app.backtest.summary import build_summary

# Sentinel for ClosedTrade regime fields the engine cannot know yet; the
# enrichment pipeline fills them in later. Kept as a constant so the long
# argument list stays readable and stays in sync if fields are renamed.
_UNKNOWN_REGIME_TAGS = {
    "gap_bucket": "unknown_gap",
    "opening_range_state": "unknown_opening_range",
    "opening_range_pct_bucket": "unknown_opening_range_pct",
    "opening_drive_return_bucket": "unknown_opening_drive_return",
    "opening_drive_close_position_bucket": "unknown_opening_drive",
    "daily_trend_state": "unknown_daily_trend",
    "relative_volume_bucket": "unknown_relative_volume",
    "signal_bar_close_location_bucket": "unknown_signal_bar_close_location",
    "signal_bar_body_pct_bucket": "unknown_signal_bar_body_pct",
}


def run_minimal_backtest(
    *,
    request: HistoricalBarsRequest,
    cache_dir: Path,
    output_path: Path | None,
    strategy: Strategy,
    quantity: Decimal = Decimal("1"),
    cost_model: BacktestCostModel | None = None,
) -> BacktestSummary:
    """Load normalized bars, run one strategy, and write a public-safe summary.

    Parameters:
        request: Provider-neutral bar request that also identifies instrument,
            timeframe, market, and session.
        cache_dir: Root directory for the local normalized bar cache.
        output_path: Optional path for the summary artifact. `None` skips writing.
        strategy: Selected strategy adapter. The runner does not import concrete
            strategy implementations.
        quantity: Fixed quantity per approved order intent for this first runner.
        cost_model: Execution-cost assumptions applied to simulated fills.

    Returns:
        A deterministic summary suitable for tests and local engineering review.
    """
    cost_model = cost_model or BacktestCostModel()
    session_config = get_market_session_config(request.market)
    store = LocalMarketDataStore(cache_dir)
    bars = store.load_bars(request, session_config)
    run_id = strategy_run_id(request=request, strategy_name=strategy.name)
    instrument_ref = InstrumentRef(
        instrument_id=request.instrument.instrument_id,
        market=request.instrument.market,
        currency=request.instrument.currency,
    )

    runner = _BacktestRunner(
        strategy=strategy,
        strategy_run_id=run_id,
        instrument_ref=instrument_ref,
        quantity=quantity,
        cost_model=cost_model,
    )
    runner.run(bars)

    closed_trades = enrich_closed_trades(
        runner.closed_trades,
        bars=bars,
        timezone=session_config.timezone,
    )
    return build_summary(
        closed_trades=closed_trades,
        decisions=runner.decisions,
        fills_count=len(runner.fills),
        risk_decisions_count=len(runner.risk_decisions),
        pending_orders=1 if runner.pending_order_intent is not None else 0,
        position=runner.position,
        average_entry_price=runner.average_entry_price,
        realized_pnl=runner.realized_pnl,
        total_commissions=runner.total_commissions,
        total_slippage_cost=runner.total_slippage_cost,
        bars=bars,
        strategy=strategy,
        cost_model=cost_model,
        request=request,
        output_path=output_path,
    )


class _BacktestRunner:
    """Per-run mutable state for the bar-by-bar engine.

    Fields are kept plain (not dataclass) because the bar loop mutates several
    of them every iteration; a frozen dataclass would be noise here.
    """

    __slots__ = (
        "strategy",
        "strategy_run_id",
        "instrument_ref",
        "quantity",
        "cost_model",
        "previous_bar",
        "position",
        "average_entry_price",
        "realized_pnl",
        "total_commissions",
        "total_slippage_cost",
        "diagnostics",
        "decisions",
        "risk_decisions",
        "fills",
        "closed_trades",
        "pending_order_intent",
        "pending_exit_reason",
    )

    def __init__(
        self,
        *,
        strategy: Strategy,
        strategy_run_id: StrategyRunId,
        instrument_ref: InstrumentRef,
        quantity: Decimal,
        cost_model: BacktestCostModel,
    ) -> None:
        self.strategy = strategy
        self.strategy_run_id = strategy_run_id
        self.instrument_ref = instrument_ref
        self.quantity = quantity
        self.cost_model = cost_model
        # Engine state initialized flat.
        self.previous_bar: Bar | None = None
        self.position = Decimal("0")
        self.average_entry_price = Decimal("0")
        self.realized_pnl = Decimal("0")
        self.total_commissions = Decimal("0")
        self.total_slippage_cost = Decimal("0")
        self.diagnostics = TradeDiagnosticsTracker()
        self.decisions = 0
        self.risk_decisions: list[RiskDecision] = []
        self.fills: list[SimulatedFill] = []
        self.closed_trades: list[ClosedTrade] = []
        self.pending_order_intent: OrderIntent | None = None
        self.pending_exit_reason: str | None = None

    def run(self, bars: Sequence[Bar]) -> None:
        """Iterate every bar: fill pending intents, update MFE/MAE, ask strategy."""
        for sequence_number, bar in enumerate(bars, start=1):
            if self.pending_order_intent is not None:
                # A close-based signal is only tradable on a later bar. Fill the
                # previously approved market intent at this bar's open to avoid
                # lookahead from using the same close that created the signal.
                self._handle_fill(
                    order_intent=self.pending_order_intent,
                    filled_at_utc=bar.timestamp_utc,
                    reference_price=Decimal(str(bar.open)),
                    exit_reason=self.pending_exit_reason or "unknown_exit_reason",
                )
                self.pending_order_intent = None
                self.pending_exit_reason = None

            # Update MFE/MAE for the open position using this bar's high/low.
            # The bar has completed (we have OHLC), so the excursion happened
            # during this bar's time window before any new decision is acted on.
            self.diagnostics.update_mfe_mae(
                bar_high=Decimal(str(bar.high)),
                bar_low=Decimal(str(bar.low)),
            )

            self._ask_strategy(bar=bar, sequence_number=sequence_number)

    def _ask_strategy(self, *, bar: Bar, sequence_number: int) -> None:
        """Run the strategy on one bar and act on the returned decision."""
        # Bar timestamps identify the start of the OHLCV window. A close-based
        # signal only exists after the bar completes, so the input reference and
        # decision time use the calculated bar close time.
        observed_at_utc = bar_close_time(bar.timeframe, bar.timestamp_utc)
        input_ref = StrategyInputRef(
            instrument=self.instrument_ref,
            timeframe=bar.timeframe,
            source="local-normalized-cache",
            observed_at_utc=observed_at_utc,
        )
        decision = self.strategy.decide(
            bar=bar,
            context=StrategyDecisionContext(
                strategy_run_id=self.strategy_run_id,
                input_ref=input_ref,
                sequence_number=sequence_number,
                previous_bar=self.previous_bar,
                position_quantity=self.position,
                average_entry_price=self.average_entry_price,
            ),
        )
        self.decisions += 1
        self.previous_bar = bar

        if decision.action == DecisionAction.HOLD:
            return

        risk_decision = RiskDecision(
            strategy_decision_id=decision.strategy_decision_id,
            outcome=risk_outcome_for_action(decision.action, self.position),
            reason="minimal_backtest_position_check",
            decided_at_utc=observed_at_utc,
            risk_decision_id=RiskDecisionId(
                f"{self.strategy_run_id.value}-risk-decision-{sequence_number:04d}"
            ),
        )
        if risk_decision.outcome != RiskOutcome.APPROVED:
            return
        self.risk_decisions.append(risk_decision)

        # The strategy stops at `StrategyDecision`; the runner translates that
        # approved decision into a broker-neutral intent that future live
        # execution can also understand.
        side = order_side_for_action(decision.action)
        order_intent = OrderIntent(
            strategy_decision_id=decision.strategy_decision_id,
            risk_decision_id=risk_decision.risk_decision_id,
            instrument=self.instrument_ref,
            side=side,
            quantity=self.quantity,
            order_type=OrderType.MARKET,
            created_at_utc=observed_at_utc,
            reason="minimal_backtest_next_bar_open",
            order_intent_id=OrderIntentId(
                f"{self.strategy_run_id.value}-order-intent-{sequence_number:04d}"
            ),
        )
        explicit_reference_price = explicit_decision_reference_price(decision.reason)
        if explicit_reference_price is not None:
            # Same-bar explicit price (e.g. break-entry signals). Apply the fill
            # immediately at the requested price instead of deferring to the next
            # bar open.
            self._handle_fill(
                order_intent=order_intent,
                filled_at_utc=bar.timestamp_utc,
                reference_price=explicit_reference_price,
                exit_reason=decision_rule_reason(decision.reason),
            )
            return
        # DeFill the market intent at the next bar open.
        self.pending_order_intent = order_intent
        if decision.action in (DecisionAction.EXIT_LONG, DecisionAction.EXIT_SHORT):
            self.pending_exit_reason = decision_rule_reason(decision.reason)

    def _handle_fill(
        self,
        *,
        order_intent: OrderIntent,
        filled_at_utc: datetime,
        reference_price: Decimal,
        exit_reason: str,
    ) -> None:
        """Simulate one fill, apply it, record the closed trade, reset tracker.

        Replaces the two near-identical fill blocks (pending next-open fill and
        explicit same-bar fill). Differences between the two paths are captured
        by ``reference_price`` and ``exit_reason`` arguments.
        """
        fill = simulate_next_open_fill(
            order_intent=order_intent,
            filled_at_utc=filled_at_utc,
            reference_price=reference_price,
            cost_model=self.cost_model,
        )
        self.fills.append(fill)
        self.total_commissions += fill.commission
        self.total_slippage_cost += fill.slippage_cost
        previous_position = self.position
        trade_pnl = closed_trade_pnl(
            fill=fill,
            position=self.position,
            average_entry_price=self.average_entry_price,
            open_trade_commissions=self.diagnostics.commissions,
        )
        self.position, self.average_entry_price, self.realized_pnl = apply_fill(
            fill=fill,
            position=self.position,
            average_entry_price=self.average_entry_price,
            realized_pnl=self.realized_pnl,
        )
        if trade_pnl is not None:
            if not self.diagnostics.is_open:
                msg = "closing fill encountered without an opening fill timestamp"
                raise ValueError(msg)
            self.closed_trades.append(
                ClosedTrade(
                    entered_at_utc=required_open_time(self.diagnostics),
                    exited_at_utc=fill.filled_at_utc,
                    exit_reason=exit_reason,
                    exit_price=fill.price,
                    quantity=fill.quantity,
                    entry_side=required_order_side(self.diagnostics.entry_side),
                    post_exit_max_favorable_pnl=Decimal("0"),
                    variant_name=strategy_variant_name(self.strategy),
                    macro_event_labels=(),
                    pnl=trade_pnl,
                    **_UNKNOWN_REGIME_TAGS,
                    **self.diagnostics.diagnostics(pnl=trade_pnl),
                )
            )
        if is_opening_fill(fill=fill, previous_position=previous_position):
            self.diagnostics.on_open(
                filled_at_utc=fill.filled_at_utc,
                side=fill.side,
                price=fill.price,
                commission=fill.commission,
                initial_stop_price=call_on_entry(self.strategy).initial_stop_price,
            )
        elif trade_pnl is not None:
            self.diagnostics.on_close()


def required_open_time(tracker: TradeDiagnosticsTracker) -> datetime:
    """Return the tracker's entered-at timestamp or fail if no trade is open.

    Tiny adapter kept here (not in fill_model) because the closed-trade build
    site is the only caller; it keeps the engine cockpit readable while
    preserving the original ``open_trade_entered_at_utc is None`` invariant.
    """
    entered = tracker.entered_at_utc
    if entered is None:
        msg = "closing fill encountered without an opening fill timestamp"
        raise ValueError(msg)
    return entered


__all__ = ["run_minimal_backtest"]
