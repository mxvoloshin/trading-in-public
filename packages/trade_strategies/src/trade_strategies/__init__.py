"""Trading strategies package."""

from trade_strategies.close_momentum import CloseMomentumStrategy
from trade_strategies.protocols import Strategy, StrategyDecisionContext
from trade_strategies.registry import get_strategy, list_strategy_names

PACKAGE_NAME = "trade_strategies"

__all__ = [
    "CloseMomentumStrategy",
    "PACKAGE_NAME",
    "Strategy",
    "StrategyDecisionContext",
    "get_strategy",
    "list_strategy_names",
]
