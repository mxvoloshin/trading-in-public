"""Backtest value objects: fills, cost models, and summary.

These records are pure dataclasses with no execution or analytics logic. The
runner (`backtest.runner`) constructs them; the analytics package
(`trade_analytics`) owns completed-trade records (`ClosedTrade`) and reads these
rows. Keeping the records isolated means new strategies do not need to edit the
engine to add report rows contributed via the diagnostics seam.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from trade_core import OrderIntentId, OrderSide


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
class CostStressScenario:
    """One execution-cost scenario for repeated backtest stress runs."""

    name: str
    cost_model: BacktestCostModel


@dataclass(frozen=True, slots=True)
class CostStressRow:
    """Compact result row for one execution-cost stress scenario."""

    scenario_name: str
    slippage_bps: Decimal
    commission_per_share: Decimal
    minimum_commission: Decimal
    closed_trades: int
    total_pnl: Decimal
    expectancy_per_trade: Decimal
    profit_factor: Decimal
    total_execution_costs: Decimal
    cost_drag_from_gross: Decimal
    gross_edge_consumed: Decimal
    median_post_exit_max_favorable_pnl: Decimal

    def to_json_dict(self) -> dict[str, str | int]:
        """Serialize the cost-stress row using JSON-safe primitives."""
        return {
            "scenario_name": self.scenario_name,
            "slippage_bps": str(self.slippage_bps),
            "commission_per_share": str(self.commission_per_share),
            "minimum_commission": str(self.minimum_commission),
            "closed_trades": self.closed_trades,
            "total_pnl": str(self.total_pnl),
            "expectancy_per_trade": str(self.expectancy_per_trade),
            "profit_factor": str(self.profit_factor),
            "total_execution_costs": str(self.total_execution_costs),
            "cost_drag_from_gross": str(self.cost_drag_from_gross),
            "gross_edge_consumed": str(self.gross_edge_consumed),
            "median_post_exit_max_favorable_pnl": str(self.median_post_exit_max_favorable_pnl),
        }


@dataclass(frozen=True, slots=True)
class CostStressReport:
    """Public-safe cost-stress report for one strategy/request pair."""

    strategy_name: str
    instrument_id: str
    timeframe: str
    rows: tuple[CostStressRow, ...]
    output_path: Path | None

    def to_json_dict(self) -> dict[str, str | list[dict[str, str | int]]]:
        """Serialize the cost-stress report using JSON-safe primitives."""
        return {
            "strategy_name": self.strategy_name,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "rows": [row.to_json_dict() for row in self.rows],
        }


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    """Public-safe summary of one minimal backtest run.

    The summary intentionally contains counts and PnL totals instead of raw
    strategy decisions or market data, so it can be written under `.data/`
    without becoming a public performance report.
    """

    strategy_name: str
    variant_name: str
    instrument_id: str
    timeframe: str
    trades: int
    long_trades: int
    short_trades: int
    gross_pnl: Decimal
    costed_pnl: Decimal
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
    max_consecutive_losing_trades: int
    average_holding_minutes: Decimal
    median_holding_minutes: Decimal
    longest_holding_minutes: int
    average_post_exit_max_favorable_pnl: Decimal
    median_post_exit_max_favorable_pnl: Decimal
    max_post_exit_max_favorable_pnl: Decimal
    avg_mfe: Decimal
    median_mfe: Decimal
    avg_mae: Decimal
    median_mae: Decimal
    avg_final_r: Decimal
    median_final_r: Decimal
    avg_max_favorable_r: Decimal
    median_max_favorable_r: Decimal
    avg_max_adverse_r: Decimal
    median_max_adverse_r: Decimal
    pct_reached_1r: Decimal
    pct_reached_2r: Decimal
    pct_reached_3r: Decimal
    pct_reached_1r_then_negative: Decimal
    worst_rolling_3_month: Decimal
    worst_rolling_6_month: Decimal
    largest_trade_pct_of_total_pnl: Decimal
    top_5_absolute_trades_pct_of_total_pnl: Decimal
    long_pnl: Decimal
    short_pnl: Decimal
    long_pf: Decimal
    short_pf: Decimal
    long_expectancy: Decimal
    short_expectancy: Decimal
    daily_breakdown: dict[str, dict[str, str | int]]
    year_breakdown: dict[str, dict[str, str | int]]
    month_breakdown: dict[str, dict[str, str | int]]
    weekday_breakdown: dict[str, dict[str, str | int]]
    time_of_day_breakdown: dict[str, dict[str, str | int]]
    side_breakdown: dict[str, dict[str, str | int]]
    exit_type_breakdown: dict[str, dict[str, str | int]]
    exit_reason_breakdown: dict[str, dict[str, str | int]]
    holding_time_breakdown: dict[str, dict[str, str | int]]
    gap_breakdown: dict[str, dict[str, str | int]]
    opening_range_breakdown: dict[str, dict[str, str | int]]
    opening_range_pct_breakdown: dict[str, dict[str, str | int]]
    opening_drive_return_breakdown: dict[str, dict[str, str | int]]
    opening_drive_close_position_breakdown: dict[str, dict[str, str | int]]
    daily_trend_breakdown: dict[str, dict[str, str | int]]
    relative_volume_breakdown: dict[str, dict[str, str | int]]
    signal_bar_close_location_breakdown: dict[str, dict[str, str | int]]
    signal_bar_body_pct_breakdown: dict[str, dict[str, str | int]]
    macro_event_day_breakdown: dict[str, dict[str, str | int]]
    macro_event_type_breakdown: dict[str, dict[str, str | int]]
    trade_contribution_breakdown: dict[str, dict[str, str | int]]
    day_contribution_breakdown: dict[str, dict[str, str | int]]
    chronological_split_breakdown: dict[str, dict[str, str | int]]
    rolling_3_month_breakdown: dict[str, dict[str, str | int]]
    rolling_6_month_breakdown: dict[str, dict[str, str | int]]
    output_path: Path | None

    def to_json_dict(self) -> dict[str, str | int | dict[str, dict[str, str | int]]]:
        """Serialize the summary using JSON-safe primitives."""
        return {
            "strategy_name": self.strategy_name,
            "variant_name": self.variant_name,
            "instrument_id": self.instrument_id,
            "timeframe": self.timeframe,
            "trades": self.trades,
            "long_trades": self.long_trades,
            "short_trades": self.short_trades,
            "gross_pnl": str(self.gross_pnl),
            "costed_pnl": str(self.costed_pnl),
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
            "max_consecutive_losing_trades": self.max_consecutive_losing_trades,
            "average_holding_minutes": str(self.average_holding_minutes),
            "median_holding_minutes": str(self.median_holding_minutes),
            "longest_holding_minutes": self.longest_holding_minutes,
            "average_post_exit_max_favorable_pnl": str(self.average_post_exit_max_favorable_pnl),
            "median_post_exit_max_favorable_pnl": str(self.median_post_exit_max_favorable_pnl),
            "max_post_exit_max_favorable_pnl": str(self.max_post_exit_max_favorable_pnl),
            "avg_mfe": str(self.avg_mfe),
            "median_mfe": str(self.median_mfe),
            "avg_mae": str(self.avg_mae),
            "median_mae": str(self.median_mae),
            "avg_final_r": str(self.avg_final_r),
            "median_final_r": str(self.median_final_r),
            "avg_max_favorable_r": str(self.avg_max_favorable_r),
            "median_max_favorable_r": str(self.median_max_favorable_r),
            "avg_max_adverse_r": str(self.avg_max_adverse_r),
            "median_max_adverse_r": str(self.median_max_adverse_r),
            "pct_reached_1r": str(self.pct_reached_1r),
            "pct_reached_2r": str(self.pct_reached_2r),
            "pct_reached_3r": str(self.pct_reached_3r),
            "pct_reached_1r_then_negative": str(self.pct_reached_1r_then_negative),
            "worst_rolling_3_month": str(self.worst_rolling_3_month),
            "worst_rolling_6_month": str(self.worst_rolling_6_month),
            "largest_trade_pct_of_total_pnl": str(self.largest_trade_pct_of_total_pnl),
            "top_5_absolute_trades_pct_of_total_pnl": str(
                self.top_5_absolute_trades_pct_of_total_pnl
            ),
            "long_pnl": str(self.long_pnl),
            "short_pnl": str(self.short_pnl),
            "long_pf": str(self.long_pf),
            "short_pf": str(self.short_pf),
            "long_expectancy": str(self.long_expectancy),
            "short_expectancy": str(self.short_expectancy),
            "daily_breakdown": self.daily_breakdown,
            "year_breakdown": self.year_breakdown,
            "month_breakdown": self.month_breakdown,
            "weekday_breakdown": self.weekday_breakdown,
            "time_of_day_breakdown": self.time_of_day_breakdown,
            "side_breakdown": self.side_breakdown,
            "exit_type_breakdown": self.exit_type_breakdown,
            "exit_reason_breakdown": self.exit_reason_breakdown,
            "holding_time_breakdown": self.holding_time_breakdown,
            "gap_breakdown": self.gap_breakdown,
            "opening_range_breakdown": self.opening_range_breakdown,
            "opening_range_pct_breakdown": self.opening_range_pct_breakdown,
            "opening_drive_return_breakdown": self.opening_drive_return_breakdown,
            "opening_drive_close_position_breakdown": (self.opening_drive_close_position_breakdown),
            "daily_trend_breakdown": self.daily_trend_breakdown,
            "relative_volume_breakdown": self.relative_volume_breakdown,
            "signal_bar_close_location_breakdown": self.signal_bar_close_location_breakdown,
            "signal_bar_body_pct_breakdown": self.signal_bar_body_pct_breakdown,
            "macro_event_day_breakdown": self.macro_event_day_breakdown,
            "macro_event_type_breakdown": self.macro_event_type_breakdown,
            "trade_contribution_breakdown": self.trade_contribution_breakdown,
            "day_contribution_breakdown": self.day_contribution_breakdown,
            "chronological_split_breakdown": self.chronological_split_breakdown,
            "rolling_3_month_breakdown": self.rolling_3_month_breakdown,
            "rolling_6_month_breakdown": self.rolling_6_month_breakdown,
        }


__all__ = [
    "BacktestCostModel",
    "BacktestSummary",
    "CostStressReport",
    "CostStressRow",
    "CostStressScenario",
    "SimulatedFill",
]
