"""Minimal backtest runner for research workflows."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from trade_core import (
    DecisionAction,
    InstrumentRef,
    OrderIntent,
    OrderIntentId,
    OrderSide,
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


@dataclass(frozen=True, slots=True)
class SimulatedFill:
    """Backtest-only fill record; broker/live execution records stay separate.

    Parameters:
        order_intent_id: Shared order-intent ID this simulated fill came from.
        filled_at_utc: UTC timestamp of the simulated fill.
        side: Buy or sell side from the broker-neutral order intent.
        quantity: Simulated filled quantity.
        reference_price: Next-bar open before execution costs.
        price: Simulated fill price after the configured slippage model.
        commission: Simulated commission charged for this fill.
    """

    order_intent_id: OrderIntentId
    filled_at_utc: datetime
    side: OrderSide
    quantity: Decimal
    reference_price: Decimal
    price: Decimal
    commission: Decimal

    @property
    def slippage_cost(self) -> Decimal:
        """Return the absolute slippage drag paid by this fill."""
        return abs(self.price - self.reference_price) * self.quantity


@dataclass(frozen=True, slots=True)
class ClosedTrade:
    """Completed simulated trade used for diagnostics and regime summaries.

    Parameters:
        entered_at_utc: UTC timestamp of the opening fill.
        exited_at_utc: UTC timestamp of the closing fill.
        exit_reason: Strategy decision reason that requested the closing fill.
        exit_price: Simulated closing fill price after slippage.
        quantity: Simulated closed quantity.
        post_exit_max_favorable_pnl: Best same-session long-side move after exit,
            measured from the simulated exit fill price.
        pnl: Net realized PnL after entry/exit commissions and slippage.
    """

    entered_at_utc: datetime
    exited_at_utc: datetime
    exit_reason: str
    exit_price: Decimal
    quantity: Decimal
    post_exit_max_favorable_pnl: Decimal
    pnl: Decimal

    @property
    def holding_minutes(self) -> int:
        """Return completed holding time in whole minutes."""
        return int((self.exited_at_utc - self.entered_at_utc).total_seconds() // 60)


@dataclass(frozen=True, slots=True)
class BacktestCostModel:
    """Simple execution-cost assumptions applied by the backtest runner.

    Parameters:
        slippage_bps: One-way slippage in basis points. Buy fills are adjusted
            upward and sell fills are adjusted downward.
        commission_per_share: Variable commission charged per simulated share.
        minimum_commission: Minimum commission charged per fill.
    """

    slippage_bps: Decimal = Decimal("0")
    commission_per_share: Decimal = Decimal("0")
    minimum_commission: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        for label, value in (
            ("slippage_bps", self.slippage_bps),
            ("commission_per_share", self.commission_per_share),
            ("minimum_commission", self.minimum_commission),
        ):
            if value < 0:
                msg = f"{label} must be greater than or equal to zero"
                raise ValueError(msg)

    def fill_price(self, *, side: OrderSide, reference_price: Decimal) -> Decimal:
        """Apply one-way slippage to a reference market price."""
        slippage_multiplier = self.slippage_bps / Decimal("10000")
        if side == OrderSide.BUY:
            return reference_price * (Decimal("1") + slippage_multiplier)
        return reference_price * (Decimal("1") - slippage_multiplier)

    def commission(self, *, quantity: Decimal) -> Decimal:
        """Return the simulated commission for one fill."""
        variable_commission = quantity * self.commission_per_share
        return max(variable_commission, self.minimum_commission)


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    """Public-safe summary of one minimal backtest run.

    The summary intentionally contains counts and PnL totals instead of raw
    strategy decisions or market data, so it can be written under `.data/`
    without becoming a public performance report.
    """

    strategy_name: str
    instrument_id: str
    timeframe: str
    bars_loaded: int
    decisions: int
    approved_orders: int
    fills: int
    pending_orders: int
    ending_position: Decimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    total_pnl: Decimal
    slippage_bps: Decimal
    commission_per_share: Decimal
    minimum_commission: Decimal
    total_commissions: Decimal
    total_slippage_cost: Decimal
    total_execution_costs: Decimal
    cost_per_closed_trade: Decimal
    closed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    expectancy_per_trade: Decimal
    expectancy_per_day: Decimal
    median_trade_pnl: Decimal
    average_win: Decimal
    average_loss: Decimal
    best_trade_pnl: Decimal
    worst_trade_pnl: Decimal
    profit_factor: Decimal
    max_drawdown: Decimal
    max_drawdown_duration_trades: int
    average_holding_minutes: Decimal
    median_holding_minutes: Decimal
    longest_holding_minutes: int
    average_post_exit_max_favorable_pnl: Decimal
    median_post_exit_max_favorable_pnl: Decimal
    max_post_exit_max_favorable_pnl: Decimal
    daily_breakdown: dict[str, dict[str, str | int]]
    time_of_day_breakdown: dict[str, dict[str, str | int]]
    exit_reason_breakdown: dict[str, dict[str, str | int]]
    holding_time_breakdown: dict[str, dict[str, str | int]]
    output_path: Path | None

    def to_json_dict(self) -> dict[str, str | int | dict[str, dict[str, str | int]]]:
        """Serialize the summary using JSON-safe primitives."""
        return {
            "strategy_name": self.strategy_name,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "bars_loaded": self.bars_loaded,
            "decisions": self.decisions,
            "approved_orders": self.approved_orders,
            "fills": self.fills,
            "pending_orders": self.pending_orders,
            "ending_position": str(self.ending_position),
            "realized_pnl": str(self.realized_pnl),
            "unrealized_pnl": str(self.unrealized_pnl),
            "total_pnl": str(self.total_pnl),
            "slippage_bps": str(self.slippage_bps),
            "commission_per_share": str(self.commission_per_share),
            "minimum_commission": str(self.minimum_commission),
            "total_commissions": str(self.total_commissions),
            "total_slippage_cost": str(self.total_slippage_cost),
            "total_execution_costs": str(self.total_execution_costs),
            "cost_per_closed_trade": str(self.cost_per_closed_trade),
            "closed_trades": self.closed_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate": str(self.win_rate),
            "expectancy_per_trade": str(self.expectancy_per_trade),
            "expectancy_per_day": str(self.expectancy_per_day),
            "median_trade_pnl": str(self.median_trade_pnl),
            "average_win": str(self.average_win),
            "average_loss": str(self.average_loss),
            "best_trade_pnl": str(self.best_trade_pnl),
            "worst_trade_pnl": str(self.worst_trade_pnl),
            "profit_factor": str(self.profit_factor),
            "max_drawdown": str(self.max_drawdown),
            "max_drawdown_duration_trades": self.max_drawdown_duration_trades,
            "average_holding_minutes": str(self.average_holding_minutes),
            "median_holding_minutes": str(self.median_holding_minutes),
            "longest_holding_minutes": self.longest_holding_minutes,
            "average_post_exit_max_favorable_pnl": str(self.average_post_exit_max_favorable_pnl),
            "median_post_exit_max_favorable_pnl": str(self.median_post_exit_max_favorable_pnl),
            "max_post_exit_max_favorable_pnl": str(self.max_post_exit_max_favorable_pnl),
            "daily_breakdown": self.daily_breakdown,
            "time_of_day_breakdown": self.time_of_day_breakdown,
            "exit_reason_breakdown": self.exit_reason_breakdown,
            "holding_time_breakdown": self.holding_time_breakdown,
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
    strategy_run_id = _strategy_run_id(request=request, strategy_name=strategy.name)
    instrument_ref = InstrumentRef(
        instrument_id=request.instrument.instrument_id,
        market=request.instrument.market,
        currency=request.instrument.currency,
    )

    previous_bar = None
    position = Decimal("0")
    average_entry_price = Decimal("0")
    realized_pnl = Decimal("0")
    total_commissions = Decimal("0")
    total_slippage_cost = Decimal("0")
    open_trade_commissions = Decimal("0")
    open_trade_entered_at_utc: datetime | None = None
    decisions = 0
    risk_decisions: list[RiskDecision] = []
    fills: list[SimulatedFill] = []
    closed_trades: list[ClosedTrade] = []
    pending_order_intent: OrderIntent | None = None
    pending_exit_reason: str | None = None

    for sequence_number, bar in enumerate(bars, start=1):
        if pending_order_intent is not None:
            # A close-based signal is only tradable on a later bar. Fill the
            # previously approved market intent at this bar's open to avoid
            # lookahead from using the same close that created the signal.
            fill = _simulate_next_open_fill(
                order_intent=pending_order_intent,
                filled_at_utc=bar.timestamp_utc,
                reference_price=Decimal(str(bar.open)),
                cost_model=cost_model,
            )
            fills.append(fill)
            total_commissions += fill.commission
            total_slippage_cost += fill.slippage_cost
            trade_pnl = _closed_trade_pnl(
                fill=fill,
                position=position,
                average_entry_price=average_entry_price,
                open_trade_commissions=open_trade_commissions,
            )
            position, average_entry_price, realized_pnl = _apply_fill(
                fill=fill,
                position=position,
                average_entry_price=average_entry_price,
                realized_pnl=realized_pnl,
            )
            if trade_pnl is not None:
                if open_trade_entered_at_utc is None:
                    msg = "closing fill encountered without an opening fill timestamp"
                    raise ValueError(msg)
                closed_trades.append(
                    ClosedTrade(
                        entered_at_utc=open_trade_entered_at_utc,
                        exited_at_utc=fill.filled_at_utc,
                        exit_reason=pending_exit_reason or "unknown_exit_reason",
                        exit_price=fill.price,
                        quantity=fill.quantity,
                        post_exit_max_favorable_pnl=Decimal("0"),
                        pnl=trade_pnl,
                    )
                )
            open_trade_commissions = (
                open_trade_commissions + fill.commission
                if fill.side == OrderSide.BUY
                else Decimal("0")
            )
            open_trade_entered_at_utc = fill.filled_at_utc if fill.side == OrderSide.BUY else None
            pending_order_intent = None
            pending_exit_reason = None

        # Bar timestamps identify the start of the OHLCV window. A close-based
        # signal only exists after the bar completes, so the input reference and
        # decision time use the calculated bar close time.
        observed_at_utc = _bar_close_time(bar.timeframe, bar.timestamp_utc)
        input_ref = StrategyInputRef(
            instrument=instrument_ref,
            timeframe=bar.timeframe,
            source="local-normalized-cache",
            observed_at_utc=observed_at_utc,
        )
        decision = strategy.decide(
            bar=bar,
            context=StrategyDecisionContext(
                strategy_run_id=strategy_run_id,
                input_ref=input_ref,
                sequence_number=sequence_number,
                previous_bar=previous_bar,
                position_quantity=position,
            ),
        )
        decisions += 1
        previous_bar = bar

        if decision.action == DecisionAction.HOLD:
            continue

        risk_decision = RiskDecision(
            strategy_decision_id=decision.strategy_decision_id,
            outcome=_risk_outcome_for_action(decision.action, position),
            reason="minimal_backtest_position_check",
            decided_at_utc=observed_at_utc,
            risk_decision_id=RiskDecisionId(
                f"{strategy_run_id.value}-risk-decision-{sequence_number:04d}"
            ),
        )
        if risk_decision.outcome != RiskOutcome.APPROVED:
            continue
        risk_decisions.append(risk_decision)

        # The strategy stops at `StrategyDecision`; the runner translates that
        # approved decision into a broker-neutral intent that future live
        # execution can also understand.
        side = OrderSide.BUY if decision.action == DecisionAction.ENTER_LONG else OrderSide.SELL
        order_intent = OrderIntent(
            strategy_decision_id=decision.strategy_decision_id,
            risk_decision_id=risk_decision.risk_decision_id,
            instrument=instrument_ref,
            side=side,
            quantity=quantity,
            order_type=OrderType.MARKET,
            created_at_utc=observed_at_utc,
            reason="minimal_backtest_next_bar_open",
            order_intent_id=OrderIntentId(
                f"{strategy_run_id.value}-order-intent-{sequence_number:04d}"
            ),
        )
        pending_order_intent = order_intent
        if decision.action == DecisionAction.EXIT_LONG:
            pending_exit_reason = _decision_rule_reason(decision.reason)

    # If the data window ends while a position is open, realized PnL alone is
    # incomplete. Mark the open position to the last close and report both parts.
    closed_trades = _with_post_exit_max_favorable_pnl(
        closed_trades,
        bars=bars,
        timezone=session_config.timezone,
    )
    unrealized_pnl = _mark_to_market_pnl(
        position=position,
        average_entry_price=average_entry_price,
        last_close=Decimal(str(bars[-1].close)) if bars else Decimal("0"),
    )
    trade_metrics = _trade_metrics(closed_trades)
    daily_breakdown = _closed_trade_breakdown(closed_trades, timezone=session_config.timezone)
    time_of_day_breakdown = _time_of_day_breakdown(
        closed_trades,
        timezone=session_config.timezone,
    )
    exit_reason_breakdown = _exit_reason_breakdown(closed_trades)
    holding_time_breakdown = _holding_time_breakdown(closed_trades)
    total_execution_costs = total_commissions + total_slippage_cost
    summary = BacktestSummary(
        strategy_name=strategy.name,
        instrument_id=request.instrument.instrument_id,
        timeframe=request.timeframe,
        bars_loaded=len(bars),
        decisions=decisions,
        approved_orders=len(risk_decisions),
        fills=len(fills),
        pending_orders=1 if pending_order_intent is not None else 0,
        ending_position=position,
        realized_pnl=realized_pnl,
        unrealized_pnl=unrealized_pnl,
        total_pnl=realized_pnl + unrealized_pnl,
        slippage_bps=cost_model.slippage_bps,
        commission_per_share=cost_model.commission_per_share,
        minimum_commission=cost_model.minimum_commission,
        total_commissions=total_commissions,
        total_slippage_cost=total_slippage_cost,
        total_execution_costs=total_execution_costs,
        cost_per_closed_trade=(
            total_execution_costs / Decimal(trade_metrics.closed_trades)
            if trade_metrics.closed_trades
            else Decimal("0")
        ),
        closed_trades=trade_metrics.closed_trades,
        winning_trades=trade_metrics.winning_trades,
        losing_trades=trade_metrics.losing_trades,
        win_rate=trade_metrics.win_rate,
        expectancy_per_trade=trade_metrics.expectancy_per_trade,
        expectancy_per_day=(
            sum((trade.pnl for trade in closed_trades), Decimal("0"))
            / Decimal(len(daily_breakdown))
            if daily_breakdown
            else Decimal("0")
        ),
        median_trade_pnl=trade_metrics.median_trade_pnl,
        average_win=trade_metrics.average_win,
        average_loss=trade_metrics.average_loss,
        best_trade_pnl=trade_metrics.best_trade_pnl,
        worst_trade_pnl=trade_metrics.worst_trade_pnl,
        profit_factor=trade_metrics.profit_factor,
        max_drawdown=trade_metrics.max_drawdown,
        max_drawdown_duration_trades=trade_metrics.max_drawdown_duration_trades,
        average_holding_minutes=trade_metrics.average_holding_minutes,
        median_holding_minutes=trade_metrics.median_holding_minutes,
        longest_holding_minutes=trade_metrics.longest_holding_minutes,
        average_post_exit_max_favorable_pnl=trade_metrics.average_post_exit_max_favorable_pnl,
        median_post_exit_max_favorable_pnl=trade_metrics.median_post_exit_max_favorable_pnl,
        max_post_exit_max_favorable_pnl=trade_metrics.max_post_exit_max_favorable_pnl,
        daily_breakdown=daily_breakdown,
        time_of_day_breakdown=time_of_day_breakdown,
        exit_reason_breakdown=exit_reason_breakdown,
        holding_time_breakdown=holding_time_breakdown,
        output_path=output_path,
    )
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(summary.to_json_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return summary


def _risk_outcome_for_action(action: DecisionAction, position: Decimal) -> RiskOutcome:
    """Approve only position transitions supported by the first runner.

    Parameters:
        action: Strategy-requested action.
        position: Current simulated position before the new order intent.
    """
    if action == DecisionAction.ENTER_LONG and position == 0:
        return RiskOutcome.APPROVED
    if action == DecisionAction.EXIT_LONG and position > 0:
        return RiskOutcome.APPROVED
    return RiskOutcome.REJECTED


def _simulate_next_open_fill(
    *,
    order_intent: OrderIntent,
    filled_at_utc: datetime,
    reference_price: Decimal,
    cost_model: BacktestCostModel,
) -> SimulatedFill:
    """Create a deterministic simulated fill at the next bar open.

    Parameters:
        order_intent: Approved broker-neutral order intent waiting to fill.
        filled_at_utc: Timestamp of the next normalized bar open.
        reference_price: Open price from that same normalized bar.
        cost_model: Slippage and commission assumptions for the fill.
    """
    return SimulatedFill(
        order_intent_id=order_intent.order_intent_id,
        filled_at_utc=filled_at_utc.astimezone(UTC),
        side=order_intent.side,
        quantity=order_intent.quantity,
        reference_price=reference_price,
        price=cost_model.fill_price(
            side=order_intent.side,
            reference_price=reference_price,
        ),
        commission=cost_model.commission(quantity=order_intent.quantity),
    )


def _apply_fill(
    *,
    fill: SimulatedFill,
    position: Decimal,
    average_entry_price: Decimal,
    realized_pnl: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    """Apply one simulated fill to position, entry price, and realized PnL.

    Parameters:
        fill: Backtest-only fill to apply.
        position: Position before the fill.
        average_entry_price: Current long entry price for the simple one-unit
            accounting model.
        realized_pnl: Realized PnL before the fill.
    """
    # The first runner supports one long unit at a time. That keeps simulated
    # execution obvious while proving the decision -> intent -> fill chain.
    if fill.side == OrderSide.BUY:
        return position + fill.quantity, fill.price, realized_pnl - fill.commission

    new_position = position - fill.quantity
    new_realized_pnl = (
        realized_pnl + (fill.price - average_entry_price) * fill.quantity - fill.commission
    )
    new_average_entry_price = Decimal("0") if new_position == 0 else average_entry_price
    return new_position, new_average_entry_price, new_realized_pnl


def _closed_trade_pnl(
    *,
    fill: SimulatedFill,
    position: Decimal,
    average_entry_price: Decimal,
    open_trade_commissions: Decimal,
) -> Decimal | None:
    """Return realized trade PnL when a fill closes a simple long position."""
    if fill.side != OrderSide.SELL or position <= 0:
        return None
    return (
        (fill.price - average_entry_price) * fill.quantity
        - open_trade_commissions
        - fill.commission
    )


def _mark_to_market_pnl(
    *,
    position: Decimal,
    average_entry_price: Decimal,
    last_close: Decimal,
) -> Decimal:
    """Calculate unrealized PnL for the open position using the last close."""
    if position == 0:
        return Decimal("0")
    return (last_close - average_entry_price) * position


def _with_post_exit_max_favorable_pnl(
    closed_trades: list[ClosedTrade],
    *,
    bars: Sequence[Bar],
    timezone: str,
) -> list[ClosedTrade]:
    """Attach the best same-session long-side move available after each exit.

    This is a diagnostic for "did we exit before the trend resumed?" It stays in
    the research runner because it needs future bars and must not affect strategy
    decisions.
    """
    zone = ZoneInfo(timezone)
    annotated_trades: list[ClosedTrade] = []
    for trade in closed_trades:
        exit_local_date = trade.exited_at_utc.astimezone(zone).date()
        future_same_session_highs = (
            Decimal(str(bar.high))
            for bar in bars
            if bar.timestamp_utc >= trade.exited_at_utc
            and bar.timestamp_utc.astimezone(zone).date() == exit_local_date
        )
        max_future_high = max(future_same_session_highs, default=trade.exit_price)
        post_exit_move = max(max_future_high - trade.exit_price, Decimal("0")) * trade.quantity
        annotated_trades.append(
            replace(
                trade,
                post_exit_max_favorable_pnl=post_exit_move,
            )
        )
    return annotated_trades


@dataclass(frozen=True, slots=True)
class _TradeMetrics:
    """Completed-trade quality metrics for the public-safe summary."""

    closed_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: Decimal
    expectancy_per_trade: Decimal
    median_trade_pnl: Decimal
    average_win: Decimal
    average_loss: Decimal
    best_trade_pnl: Decimal
    worst_trade_pnl: Decimal
    profit_factor: Decimal
    max_drawdown: Decimal
    max_drawdown_duration_trades: int
    average_holding_minutes: Decimal
    median_holding_minutes: Decimal
    longest_holding_minutes: int
    average_post_exit_max_favorable_pnl: Decimal
    median_post_exit_max_favorable_pnl: Decimal
    max_post_exit_max_favorable_pnl: Decimal


def _trade_metrics(closed_trades: list[ClosedTrade]) -> _TradeMetrics:
    """Calculate simple distribution metrics from completed trade PnL values."""
    closed_trade_pnls = [trade.pnl for trade in closed_trades]
    holding_minutes = [Decimal(trade.holding_minutes) for trade in closed_trades]
    post_exit_max_favorable_pnls = [trade.post_exit_max_favorable_pnl for trade in closed_trades]
    winning_pnls = [pnl for pnl in closed_trade_pnls if pnl > 0]
    losing_pnls = [pnl for pnl in closed_trade_pnls if pnl < 0]
    gross_profit = sum(winning_pnls, Decimal("0"))
    gross_loss = abs(sum(losing_pnls, Decimal("0")))
    closed_trade_count = len(closed_trade_pnls)

    return _TradeMetrics(
        closed_trades=closed_trade_count,
        winning_trades=len(winning_pnls),
        losing_trades=len(losing_pnls),
        win_rate=(
            Decimal(len(winning_pnls)) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        expectancy_per_trade=(
            sum(closed_trade_pnls, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_trade_pnl=_median_decimal(closed_trade_pnls),
        average_win=(gross_profit / Decimal(len(winning_pnls)) if winning_pnls else Decimal("0")),
        average_loss=(
            sum(losing_pnls, Decimal("0")) / Decimal(len(losing_pnls))
            if losing_pnls
            else Decimal("0")
        ),
        best_trade_pnl=max(closed_trade_pnls) if closed_trade_pnls else Decimal("0"),
        worst_trade_pnl=min(closed_trade_pnls) if closed_trade_pnls else Decimal("0"),
        profit_factor=(
            gross_profit / gross_loss if gross_profit > 0 and gross_loss > 0 else Decimal("0")
        ),
        max_drawdown=_max_drawdown(closed_trade_pnls),
        max_drawdown_duration_trades=_max_drawdown_duration_trades(closed_trade_pnls),
        average_holding_minutes=(
            sum(holding_minutes, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_holding_minutes=_median_decimal(holding_minutes),
        longest_holding_minutes=(
            max(trade.holding_minutes for trade in closed_trades) if closed_trades else 0
        ),
        average_post_exit_max_favorable_pnl=(
            sum(post_exit_max_favorable_pnls, Decimal("0")) / Decimal(closed_trade_count)
            if closed_trade_count
            else Decimal("0")
        ),
        median_post_exit_max_favorable_pnl=_median_decimal(post_exit_max_favorable_pnls),
        max_post_exit_max_favorable_pnl=(
            max(post_exit_max_favorable_pnls) if post_exit_max_favorable_pnls else Decimal("0")
        ),
    )


def _median_decimal(values: list[Decimal]) -> Decimal:
    """Return the median value while preserving Decimal precision."""
    if not values:
        return Decimal("0")
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2 == 1:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / Decimal("2")


def _max_drawdown(closed_trade_pnls: list[Decimal]) -> Decimal:
    """Calculate max realized drawdown from the closed-trade equity curve."""
    equity = Decimal("0")
    peak = Decimal("0")
    max_drawdown = Decimal("0")
    for trade_pnl in closed_trade_pnls:
        equity += trade_pnl
        peak = max(peak, equity)
        max_drawdown = min(max_drawdown, equity - peak)
    return max_drawdown


def _max_drawdown_duration_trades(closed_trade_pnls: list[Decimal]) -> int:
    """Return the longest completed-trade count spent below an equity peak."""
    equity = Decimal("0")
    peak = Decimal("0")
    current_duration = 0
    max_duration = 0
    for trade_pnl in closed_trade_pnls:
        equity += trade_pnl
        if equity >= peak:
            peak = equity
            current_duration = 0
            continue
        current_duration += 1
        max_duration = max(max_duration, current_duration)
    return max_duration


def _closed_trade_breakdown(
    closed_trades: list[ClosedTrade],
    *,
    timezone: str,
) -> dict[str, dict[str, str | int]]:
    """Group completed trades by market-local exit date."""
    zone = ZoneInfo(timezone)
    buckets: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        local_date = trade.exited_at_utc.astimezone(zone).date().isoformat()
        buckets.setdefault(local_date, []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _time_of_day_breakdown(
    closed_trades: list[ClosedTrade],
    *,
    timezone: str,
) -> dict[str, dict[str, str | int]]:
    """Group completed trades into 30-minute market-local exit buckets."""
    zone = ZoneInfo(timezone)
    buckets: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        local_exit = trade.exited_at_utc.astimezone(zone)
        bucket_minute = 30 if local_exit.minute >= 30 else 0
        bucket_start = local_exit.replace(
            minute=bucket_minute,
            second=0,
            microsecond=0,
        )
        bucket_end = bucket_start + timedelta(minutes=30)
        label = f"{bucket_start:%H:%M}-{bucket_end:%H:%M}"
        buckets.setdefault(label, []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _exit_reason_breakdown(closed_trades: list[ClosedTrade]) -> dict[str, dict[str, str | int]]:
    """Group completed trades by the strategy rule that requested the exit."""
    buckets: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        buckets.setdefault(trade.exit_reason, []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _holding_time_breakdown(closed_trades: list[ClosedTrade]) -> dict[str, dict[str, str | int]]:
    """Group completed trades by elapsed time between entry and exit fills."""
    buckets: dict[str, list[ClosedTrade]] = {}
    for trade in closed_trades:
        buckets.setdefault(_holding_time_bucket(trade.holding_minutes), []).append(trade)
    return {bucket: _trade_bucket_summary(trades) for bucket, trades in sorted(buckets.items())}


def _holding_time_bucket(holding_minutes: int) -> str:
    """Return a stable human-readable holding-time bucket label."""
    if holding_minutes < 30:
        return "00-30m"
    if holding_minutes < 60:
        return "30-60m"
    if holding_minutes < 120:
        return "60-120m"
    return "120m+"


def _trade_bucket_summary(trades: list[ClosedTrade]) -> dict[str, str | int]:
    """Summarize one bucket of completed trades."""
    pnls = [trade.pnl for trade in trades]
    holding_minutes = [Decimal(trade.holding_minutes) for trade in trades]
    post_exit_max_favorable_pnls = [trade.post_exit_max_favorable_pnl for trade in trades]
    total_pnl = sum(pnls, Decimal("0"))
    winning_trades = sum(1 for pnl in pnls if pnl > 0)
    losing_trades = sum(1 for pnl in pnls if pnl < 0)
    return {
        "closed_trades": len(trades),
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate": str(Decimal(winning_trades) / Decimal(len(pnls)) if pnls else Decimal("0")),
        "total_pnl": str(total_pnl),
        "expectancy": str(total_pnl / Decimal(len(pnls)) if pnls else Decimal("0")),
        "average_holding_minutes": str(
            sum(holding_minutes, Decimal("0")) / Decimal(len(holding_minutes))
            if holding_minutes
            else Decimal("0")
        ),
        "median_holding_minutes": str(_median_decimal(holding_minutes)),
        "average_post_exit_max_favorable_pnl": str(
            sum(post_exit_max_favorable_pnls, Decimal("0"))
            / Decimal(len(post_exit_max_favorable_pnls))
            if post_exit_max_favorable_pnls
            else Decimal("0")
        ),
        "median_post_exit_max_favorable_pnl": str(_median_decimal(post_exit_max_favorable_pnls)),
        "max_post_exit_max_favorable_pnl": str(
            max(post_exit_max_favorable_pnls) if post_exit_max_favorable_pnls else Decimal("0")
        ),
    }


def _decision_rule_reason(reason: str) -> str:
    """Strip instrument tagging from a strategy reason for report grouping."""
    return reason.split(":", maxsplit=1)[0]


def _bar_close_time(timeframe: str, timestamp_utc: datetime) -> datetime:
    """Return when a bar's close-based signal becomes observable.

    Parameters:
        timeframe: Market-data timeframe string, currently supporting `*Min`.
        timestamp_utc: UTC timestamp at the start of the bar.
    """
    if timeframe.endswith("Min"):
        minutes = int(timeframe.removesuffix("Min"))
        return timestamp_utc.astimezone(UTC) + timedelta(minutes=minutes)
    msg = f"unsupported minimal backtest timeframe: {timeframe}"
    raise ValueError(msg)


def _strategy_run_id(*, request: HistoricalBarsRequest, strategy_name: str) -> StrategyRunId:
    """Build a deterministic run ID from strategy and market-data inputs."""
    start = request.start_utc.strftime("%Y%m%dT%H%M%SZ")
    end = request.end_utc.strftime("%Y%m%dT%H%M%SZ")
    value = (
        f"backtest-{strategy_name}-{request.instrument.instrument_id}-"
        f"{request.timeframe}-{start}-{end}"
    )
    return StrategyRunId(value.lower())
