"""Trading strategies package."""

from trade_strategies.close_momentum import CloseMomentumStrategy
from trade_strategies.protocols import Strategy, StrategyDecisionContext
from trade_strategies.registry import get_strategy, list_strategy_names
from trade_strategies.spy_opening_range_breakout import (
    SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy,
    SpyOpeningRangeBreakoutTrendHoldStrategy,
    SpyOrbAtrTrail1_0Strategy,
    SpyOrbAtrTrail1_5Strategy,
    SpyOrbAtrTrail2_0Strategy,
    SpyOrbAtrTrailStrategy,
    SpyOrbBreakEvenAfter1RStrategy,
    SpyOrbStructureTrailStrategy,
)

PACKAGE_NAME = "trade_strategies"

__all__ = [
    "CloseMomentumStrategy",
    "SpyOpeningRangeBreakoutMidpointStopMaxOneStrategy",
    "SpyOpeningRangeBreakoutTrendHoldStrategy",
    "SpyOrbAtrTrail1_0Strategy",
    "SpyOrbAtrTrail1_5Strategy",
    "SpyOrbAtrTrail2_0Strategy",
    "SpyOrbAtrTrailStrategy",
    "SpyOrbBreakEvenAfter1RStrategy",
    "SpyOrbStructureTrailStrategy",
    "PACKAGE_NAME",
    "Strategy",
    "StrategyDecisionContext",
    "get_strategy",
    "list_strategy_names",
]
