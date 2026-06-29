"""Minimal backtest runner for research workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

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
from trade_data import HistoricalBarsRequest, LocalMarketDataStore
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
        price: Simulated fill price from normalized market data.
    """

    order_intent_id: OrderIntentId
    filled_at_utc: datetime
    side: OrderSide
    quantity: Decimal
    price: Decimal


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
    output_path: Path | None

    def to_json_dict(self) -> dict[str, str | int]:
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
        }


def run_minimal_backtest(
    *,
    request: HistoricalBarsRequest,
    cache_dir: Path,
    output_path: Path | None,
    strategy: Strategy,
    quantity: Decimal = Decimal("1"),
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

    Returns:
        A deterministic summary suitable for tests and local engineering review.
    """
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
    decisions = 0
    risk_decisions: list[RiskDecision] = []
    fills: list[SimulatedFill] = []
    pending_order_intent: OrderIntent | None = None

    for sequence_number, bar in enumerate(bars, start=1):
        if pending_order_intent is not None:
            # A close-based signal is only tradable on a later bar. Fill the
            # previously approved market intent at this bar's open to avoid
            # lookahead from using the same close that created the signal.
            fill = _simulate_next_open_fill(
                order_intent=pending_order_intent,
                filled_at_utc=bar.timestamp_utc,
                price=Decimal(str(bar.open)),
            )
            fills.append(fill)
            position, average_entry_price, realized_pnl = _apply_fill(
                fill=fill,
                position=position,
                average_entry_price=average_entry_price,
                realized_pnl=realized_pnl,
            )
            pending_order_intent = None

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

    # If the data window ends while a position is open, realized PnL alone is
    # incomplete. Mark the open position to the last close and report both parts.
    unrealized_pnl = _mark_to_market_pnl(
        position=position,
        average_entry_price=average_entry_price,
        last_close=Decimal(str(bars[-1].close)) if bars else Decimal("0"),
    )
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
    price: Decimal,
) -> SimulatedFill:
    """Create a deterministic simulated fill at the next bar open.

    Parameters:
        order_intent: Approved broker-neutral order intent waiting to fill.
        filled_at_utc: Timestamp of the next normalized bar open.
        price: Open price from that same normalized bar.
    """
    return SimulatedFill(
        order_intent_id=order_intent.order_intent_id,
        filled_at_utc=filled_at_utc.astimezone(UTC),
        side=order_intent.side,
        quantity=order_intent.quantity,
        price=price,
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
        return position + fill.quantity, fill.price, realized_pnl

    new_position = position - fill.quantity
    new_realized_pnl = realized_pnl + (fill.price - average_entry_price) * fill.quantity
    new_average_entry_price = Decimal("0") if new_position == 0 else average_entry_price
    return new_position, new_average_entry_price, new_realized_pnl


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
