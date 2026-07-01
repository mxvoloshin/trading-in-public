"""CLI/engine wiring helpers: deterministic IDs, bar-close times, reason parsing.

These helpers translate between the public-facing strategy/engine concepts
(run IDs, decision reasons) and broker-neutral records. They live separately
from the engine so the engine itself stays free of string contracts.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from trade_core import StrategyRunId
from trade_data import HistoricalBarsRequest
from trade_strategies import Strategy


def strategy_family_name(strategy: Strategy) -> str:
    """Return the report-level family name for a strategy instance."""
    return str(getattr(strategy, "family_name", strategy.name))


def strategy_variant_name(strategy: Strategy) -> str:
    """Return the report-level variant name for a strategy instance."""
    return str(getattr(strategy, "variant_name", strategy.name))


def decision_rule_reason(reason: str) -> str:
    """Strip instrument tagging from a strategy reason for report grouping."""
    return reason.split(":", maxsplit=1)[0]


def explicit_decision_reference_price(reason: str) -> Decimal | None:
    """Extract an explicit same-bar fill reference price from a decision reason.

    Some strategies request fills at a specific price (e.g. break-entry signals)
    by encoding ``rule@price`` in the decision reason. Returns ``None`` when no
    explicit price is present; the engine then falls back to next-bar open.
    """
    rule_reason = decision_rule_reason(reason)
    if "@" not in rule_reason:
        return None
    _, reference_price = rule_reason.rsplit("@", maxsplit=1)
    return Decimal(reference_price)


def bar_close_time(timeframe: str, timestamp_utc: datetime) -> datetime:
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


def strategy_run_id(*, request: HistoricalBarsRequest, strategy_name: str) -> StrategyRunId:
    """Build a deterministic run ID from strategy and market-data inputs."""
    start = request.start_utc.strftime("%Y%m%dT%H%M%SZ")
    end = request.end_utc.strftime("%Y%m%dT%H%M%SZ")
    value = (
        f"backtest-{strategy_name}-{request.instrument.instrument_id}-"
        f"{request.timeframe}-{start}-{end}"
    )
    return StrategyRunId(value.lower())


__all__ = [
    "bar_close_time",
    "decision_rule_reason",
    "explicit_decision_reference_price",
    "strategy_family_name",
    "strategy_run_id",
    "strategy_variant_name",
]
