"""Built-in strategy registry."""

from __future__ import annotations

from collections.abc import Callable

from trade_strategies.close_momentum import CloseMomentumStrategy
from trade_strategies.protocols import Strategy
from trade_strategies.spy_opening_range_breakout import (
    SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy,
    SpyOpeningRangeBreakoutMidpointStopMaxTwoStrategy,
    SpyOpeningRangeBreakoutOppositeStopMaxOneStrategy,
    SpyOpeningRangeBreakoutOppositeStopMaxTwoStrategy,
)

StrategyFactory = Callable[[], Strategy]

_STRATEGIES: dict[str, StrategyFactory] = {
    CloseMomentumStrategy.name: CloseMomentumStrategy,
    SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy.name: (
        SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy
    ),
    SpyOpeningRangeBreakoutMidpointStopMaxTwoStrategy.name: (
        SpyOpeningRangeBreakoutMidpointStopMaxTwoStrategy
    ),
    SpyOpeningRangeBreakoutOppositeStopMaxOneStrategy.name: (
        SpyOpeningRangeBreakoutOppositeStopMaxOneStrategy
    ),
    SpyOpeningRangeBreakoutOppositeStopMaxTwoStrategy.name: (
        SpyOpeningRangeBreakoutOppositeStopMaxTwoStrategy
    ),
}


def get_strategy(name: str) -> Strategy:
    """Return a fresh built-in strategy instance by registry name.

    Parameters:
        name: User-facing strategy name, such as `close-momentum`.

    Raises:
        ValueError: If the requested strategy is not registered.
    """
    normalized_name = name.strip().lower()
    try:
        strategy_factory = _STRATEGIES[normalized_name]
    except KeyError as exc:
        available = ", ".join(list_strategy_names())
        msg = f"unknown strategy {name!r}; available strategies: {available}"
        raise ValueError(msg) from exc
    return strategy_factory()


def list_strategy_names() -> tuple[str, ...]:
    """Return strategy names accepted by the research CLI."""
    return tuple(sorted(_STRATEGIES))
