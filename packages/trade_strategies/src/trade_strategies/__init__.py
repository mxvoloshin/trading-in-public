"""Trading strategies package."""

from trade_strategies.close_momentum import CloseMomentumStrategy
from trade_strategies.protocols import Strategy, StrategyDecisionContext
from trade_strategies.registry import get_strategy, list_strategy_names
from trade_strategies.spy_vwap_pullback import (
    DailyContextVwapReclaimStrategy,
    DynamicVwapDistanceReclaimStrategy,
    EntryFilteredTrendDayVwapReclaimStrategy,
    GapAndGoVwapPullbackStrategy,
    OpeningDriveQualityVwapReclaimStrategy,
    RvolBucketVwapReclaimStrategy,
    SpyVwapPullbackStrategy,
    SpyVwapTrendContinuationLongShortBaseStrategy,
    SymmetricSpyVwapPullbackStrategy,
    TrendDayVwapReclaimStrategy,
)

PACKAGE_NAME = "trade_strategies"

__all__ = [
    "CloseMomentumStrategy",
    "DailyContextVwapReclaimStrategy",
    "DynamicVwapDistanceReclaimStrategy",
    "EntryFilteredTrendDayVwapReclaimStrategy",
    "GapAndGoVwapPullbackStrategy",
    "OpeningDriveQualityVwapReclaimStrategy",
    "PACKAGE_NAME",
    "RvolBucketVwapReclaimStrategy",
    "SpyVwapTrendContinuationLongShortBaseStrategy",
    "SpyVwapPullbackStrategy",
    "Strategy",
    "StrategyDecisionContext",
    "SymmetricSpyVwapPullbackStrategy",
    "TrendDayVwapReclaimStrategy",
    "get_strategy",
    "list_strategy_names",
]
