"""Backtest fill accounting: simulate fills and update position/PnL.

Pure functions that translate broker-neutral ``OrderIntent`` objects into
``SimulatedFill`` records and apply them to a one-unit-per-direction position
accounting model. Nothing here reads strategy state or writes reports.

Public helpers re-exported by ``backtest.runner``:
    - simulate_next_open_fill
    - apply_fill
    - closed_trade_pnl
    - is_opening_fill
    - mark_to_market_pnl
    - risk_outcome_for_action
    - order_side_for_action
    - required_order_side
    - extract_stop_from_context
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from trade_core import (
    DecisionAction,
    OrderIntent,
    OrderSide,
    RiskOutcome,
)
from trade_strategies import OpenTradeDiagnostics, Strategy

from trade_research_app.backtest.records import BacktestCostModel, SimulatedFill


def risk_outcome_for_action(action: DecisionAction, position: Decimal) -> RiskOutcome:
    """Approve only position transitions supported by the first runner.

    Parameters:
        action: Strategy-requested action.
        position: Current simulated position before the new order intent.
    """
    if action == DecisionAction.ENTER_LONG and position == 0:
        return RiskOutcome.APPROVED
    if action == DecisionAction.EXIT_LONG and position > 0:
        return RiskOutcome.APPROVED
    if action == DecisionAction.ENTER_SHORT and position == 0:
        return RiskOutcome.APPROVED
    if action == DecisionAction.EXIT_SHORT and position < 0:
        return RiskOutcome.APPROVED
    return RiskOutcome.REJECTED


def order_side_for_action(action: DecisionAction) -> OrderSide:
    """Translate a strategy action into the order side needed to execute it."""
    if action in (DecisionAction.ENTER_LONG, DecisionAction.EXIT_SHORT):
        return OrderSide.BUY
    if action in (DecisionAction.EXIT_LONG, DecisionAction.ENTER_SHORT):
        return OrderSide.SELL
    msg = f"cannot create an order side for action {action}"
    raise ValueError(msg)


def simulate_next_open_fill(
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


def apply_fill(
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
        average_entry_price: Current entry price for the simple one-unit
            accounting model.
        realized_pnl: Realized PnL before the fill.
    """
    if fill.side == OrderSide.BUY:
        if position < 0:
            new_position = position + fill.quantity
            new_realized_pnl = (
                realized_pnl + (average_entry_price - fill.price) * fill.quantity - fill.commission
            )
            new_average_entry_price = Decimal("0") if new_position == 0 else average_entry_price
            return new_position, new_average_entry_price, new_realized_pnl
        return position + fill.quantity, fill.price, realized_pnl - fill.commission

    if position == 0:
        return position - fill.quantity, fill.price, realized_pnl - fill.commission

    new_position = position - fill.quantity
    new_realized_pnl = (
        realized_pnl + (fill.price - average_entry_price) * fill.quantity - fill.commission
    )
    new_average_entry_price = Decimal("0") if new_position == 0 else average_entry_price
    return new_position, new_average_entry_price, new_realized_pnl


def closed_trade_pnl(
    *,
    fill: SimulatedFill,
    position: Decimal,
    average_entry_price: Decimal,
    open_trade_commissions: Decimal,
) -> Decimal | None:
    """Return realized trade PnL when a fill closes a simple one-unit position."""
    if fill.side == OrderSide.SELL and position > 0:
        return (
            (fill.price - average_entry_price) * fill.quantity
            - open_trade_commissions
            - fill.commission
        )
    if fill.side == OrderSide.BUY and position < 0:
        return (
            (average_entry_price - fill.price) * fill.quantity
            - open_trade_commissions
            - fill.commission
        )
    return None


def is_opening_fill(*, fill: SimulatedFill, previous_position: Decimal) -> bool:
    """Return whether a fill opens a new long or short position."""
    if previous_position != 0:
        return False
    return fill.side in (OrderSide.BUY, OrderSide.SELL)


def call_on_entry(strategy: Strategy) -> OpenTradeDiagnostics:
    """Ask the strategy for diagnostics context for the trade just opened.

    Strategies that implement ``on_entry`` return their initial stop price and
    any other diagnostics they own. Strategies that don't implement the hook
    get a default ``OpenTradeDiagnostics`` with zero stop — R multiples are
    then undefined. This replaces the former ``getattr(strategy, "_state",
    "active_stop")`` pattern with a named protocol seam.
    """
    on_entry = getattr(strategy, "on_entry", None)
    if on_entry is not None:
        return on_entry()
    return OpenTradeDiagnostics()


def required_order_side(value: OrderSide | None) -> OrderSide:
    """Return the saved trade entry side or fail if execution bookkeeping broke."""
    if value is None:
        msg = "open_trade_entry_side is required when closing a trade"
        raise ValueError(msg)
    return value


def mark_to_market_pnl(
    *,
    position: Decimal,
    average_entry_price: Decimal,
    last_close: Decimal,
) -> Decimal:
    """Calculate unrealized PnL for the open position using the last close."""
    if position == 0:
        return Decimal("0")
    if position > 0:
        return (last_close - average_entry_price) * position
    return (average_entry_price - last_close) * abs(position)


__all__ = [
    "apply_fill",
    "call_on_entry",
    "closed_trade_pnl",
    "is_opening_fill",
    "mark_to_market_pnl",
    "order_side_for_action",
    "required_order_side",
    "risk_outcome_for_action",
    "simulate_next_open_fill",
]
