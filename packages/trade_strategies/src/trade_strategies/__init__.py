"""Trading strategies package."""

from trade_strategies.close_momentum import CloseMomentumStrategy
from trade_strategies.protocols import Strategy, StrategyDecisionContext
from trade_strategies.registry import get_strategy, list_strategy_names
from trade_strategies.spy_vwap_pullback import (
    DailyContextVwapReclaimStrategy,
    EntryFilteredTrendDayVwapReclaimStrategy,
    GapAndGoVwapPullbackStrategy,
    OpeningDriveQualityVwapReclaimStrategy,
    RvolBucketVwapReclaimStrategy,
    SpyVwapPullbackStrategy,
    SymmetricSpyVwapPullbackStrategy,
    TrendDayVwapReclaimStrategy,
)

PACKAGE_NAME = "trade_strategies"

__all__ = [
    "CloseMomentumStrategy",
    "DailyContextVwapReclaimStrategy",
    "EntryFilteredTrendDayVwapReclaimStrategy",
    "GapAndGoVwapPullbackStrategy",
    "OpeningDriveQualityVwapReclaimStrategy",
    "PACKAGE_NAME",
    "RvolBucketVwapReclaimStrategy",
    "SpyVwapPullbackStrategy",
    "Strategy",
    "StrategyDecisionContext",
    "SymmetricSpyVwapPullbackStrategy",
    "TrendDayVwapReclaimStrategy",
    "get_strategy",
    "list_strategy_names",
]
