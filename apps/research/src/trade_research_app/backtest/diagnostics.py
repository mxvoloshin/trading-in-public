"""Per-trade diagnostics tracker: MFE/MAE while a position is open.

Encapsulates the bar-by-bar ``open_trade_*`` state the inline loop previously
carried as 14 local variables. The tracker advances with each completed bar
while a position is open, and the engine queries it at entry/close time to
build ``ClosedTrade`` diagnostics.

R multiples are derived from the initial stop price captured at entry. R is
``|entry_price - initial_stop_price|``; favorable R is ``MFE / R`` and adverse
R is ``MAE / R``.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from trade_analytics.metrics import _compute_mfe_mae_r_diagnostics, _TradeDiagnostics
from trade_core import OrderSide

from trade_research_app.backtest.fill_model import required_order_side


class TradeDiagnosticsTracker:
    """Tracks the in-flight trade's entry/stop/MFE/MAE while a position is open.

    The engine constructs one of these at run start in a flat state. Calling
    :meth:`on_open` at an opening fill resets all fields to that trade's entry
    facts; :meth:`update_mfe_mae` advances MFE/MAE from each subsequent bar's
    high/low; :meth:`diagnostics` returns the per-trade typed payload built by
    ``_compute_mfe_mae_r_diagnostics`` at close time.
    """

    __slots__ = (
        "commissions",
        "entered_at_utc",
        "entry_side",
        "entry_price",
        "initial_stop_price",
        "mfe",
        "mae",
    )

    def __init__(self) -> None:
        self.commissions: Decimal = Decimal("0")
        self.entered_at_utc: datetime | None = None
        self.entry_side: OrderSide | None = None
        self.entry_price: Decimal = Decimal("0")
        self.initial_stop_price: Decimal = Decimal("0")
        self.mfe: Decimal = Decimal("0")
        self.mae: Decimal = Decimal("0")

    @property
    def is_open(self) -> bool:
        """Return whether a position is currently open for this trade."""
        return self.entered_at_utc is not None

    def on_open(
        self,
        *,
        filled_at_utc: datetime,
        side: OrderSide,
        price: Decimal,
        commission: Decimal,
        initial_stop_price: Decimal,
    ) -> None:
        """Reset the tracker for a new opening fill."""
        self.commissions = commission
        self.entered_at_utc = filled_at_utc
        self.entry_side = side
        self.entry_price = price
        self.initial_stop_price = initial_stop_price
        self.mfe = Decimal("0")
        self.mae = Decimal("0")

    def on_close(self) -> None:
        """Reset the tracker back to the flat state after a closing fill."""
        self.commissions = Decimal("0")
        self.entered_at_utc = None
        self.entry_side = None
        self.entry_price = Decimal("0")
        self.initial_stop_price = Decimal("0")
        self.mfe = Decimal("0")
        self.mae = Decimal("0")

    def update_mfe_mae(self, *, bar_high: Decimal, bar_low: Decimal) -> None:
        """Advance MFE/MAE from one completed bar while a position is open."""
        if self.entry_price == 0:
            # No open position or degenerate entry price; ignore safely.
            return
        if self.entry_side == OrderSide.BUY:
            favorable = bar_high - self.entry_price
            adverse = self.entry_price - bar_low
        else:
            # SHORT: favorable is downward, adverse is upward.
            favorable = self.entry_price - bar_low
            adverse = bar_high - self.entry_price
        self.mfe = max(self.mfe, favorable)
        self.mae = max(self.mae, adverse)

    def diagnostics(self, *, pnl: Decimal) -> _TradeDiagnostics:
        """Return the typed R-multiple payload for the closing trade."""
        return _compute_mfe_mae_r_diagnostics(
            entry_price=self.entry_price,
            initial_stop_price=self.initial_stop_price,
            mfe=self.mfe,
            mae=self.mae,
            pnl=pnl,
            entry_side=required_order_side(self.entry_side),
        )


__all__ = ["TradeDiagnosticsTracker"]
