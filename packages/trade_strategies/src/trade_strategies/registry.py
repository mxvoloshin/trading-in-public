"""Built-in strategy registry."""

from __future__ import annotations

from collections.abc import Callable

from trade_strategies.close_momentum import CloseMomentumStrategy
from trade_strategies.protocols import Strategy
from trade_strategies.spy_vwap_pullback import (
    DailyContextVwapReclaimStrategy,
    DynamicVwapDistanceReclaimStrategy,
    EntryFilteredTrendDayVwapReclaimStrategy,
    GapAndGoVwapPullbackStrategy,
    OpeningDriveQualityVwapReclaimStrategy,
    RvolBucketVwapReclaimStrategy,
    SpyVwapPullbackStrategy,
    SpyVwapRangeReversionOneAndHalfAtrBandStrategy,
    SpyVwapRangeReversionOneAtrBandStrategy,
    SpyVwapRangeReversionStrategy,
    SpyVwapTrendContinuationActiveRvolFilterStrategy,
    SpyVwapTrendContinuationAtrDistanceFilterStrategy,
    SpyVwapTrendContinuationBasicSignalQualityFilterStrategy,
    SpyVwapTrendContinuationDailyTrendFilterStrategy,
    SpyVwapTrendContinuationInitialStopStrategy,
    SpyVwapTrendContinuationLongShortBaseStrategy,
    SpyVwapTrendContinuationLooseRvolFilterStrategy,
    SpyVwapTrendContinuationNormalToActiveRvolFilterStrategy,
    SpyVwapTrendContinuationOneAndHalfRTargetStrategy,
    SpyVwapTrendContinuationOneRTargetStrategy,
    SpyVwapTrendContinuationOneRTargetTimeStopStrategy,
    SpyVwapTrendContinuationOpeningDriveFilterStrategy,
    SpyVwapTrendContinuationOpeningRangeConfluenceFilterStrategy,
    SpyVwapTrendContinuationOpeningRangeConfluenceLooseFilterStrategy,
    SpyVwapTrendContinuationOpeningRangeConfluenceStrictFilterStrategy,
    SpyVwapTrendContinuationSignalBreakEntryStrategy,
    SpyVwapTrendContinuationSignalQualityBreakEntryStrategy,
    SpyVwapTrendContinuationStrongSignalQualityFilterStrategy,
    SpyVwapTrendContinuationTimeStopSixBarStrategy,
    SpyVwapTrendContinuationTimeStopStrategy,
    SpyVwapTrendContinuationTimeStopThreeBarStrategy,
    SpyVwapTrendContinuationTwoRTargetStrategy,
    SymmetricSpyVwapPullbackStrategy,
    TrendDayVwapReclaimStrategy,
)

StrategyFactory = Callable[[], Strategy]

_STRATEGIES: dict[str, StrategyFactory] = {
    CloseMomentumStrategy.name: CloseMomentumStrategy,
    SpyVwapPullbackStrategy.name: SpyVwapPullbackStrategy,
    SymmetricSpyVwapPullbackStrategy.name: SymmetricSpyVwapPullbackStrategy,
    TrendDayVwapReclaimStrategy.name: TrendDayVwapReclaimStrategy,
    EntryFilteredTrendDayVwapReclaimStrategy.name: EntryFilteredTrendDayVwapReclaimStrategy,
    GapAndGoVwapPullbackStrategy.name: GapAndGoVwapPullbackStrategy,
    DailyContextVwapReclaimStrategy.name: DailyContextVwapReclaimStrategy,
    OpeningDriveQualityVwapReclaimStrategy.name: OpeningDriveQualityVwapReclaimStrategy,
    RvolBucketVwapReclaimStrategy.name: RvolBucketVwapReclaimStrategy,
    DynamicVwapDistanceReclaimStrategy.name: DynamicVwapDistanceReclaimStrategy,
    SpyVwapRangeReversionStrategy.name: SpyVwapRangeReversionStrategy,
    SpyVwapRangeReversionOneAtrBandStrategy.name: SpyVwapRangeReversionOneAtrBandStrategy,
    SpyVwapRangeReversionOneAndHalfAtrBandStrategy.name: (
        SpyVwapRangeReversionOneAndHalfAtrBandStrategy
    ),
    SpyVwapTrendContinuationLongShortBaseStrategy.name: (
        SpyVwapTrendContinuationLongShortBaseStrategy
    ),
    SpyVwapTrendContinuationDailyTrendFilterStrategy.name: (
        SpyVwapTrendContinuationDailyTrendFilterStrategy
    ),
    SpyVwapTrendContinuationOpeningDriveFilterStrategy.name: (
        SpyVwapTrendContinuationOpeningDriveFilterStrategy
    ),
    SpyVwapTrendContinuationLooseRvolFilterStrategy.name: (
        SpyVwapTrendContinuationLooseRvolFilterStrategy
    ),
    SpyVwapTrendContinuationActiveRvolFilterStrategy.name: (
        SpyVwapTrendContinuationActiveRvolFilterStrategy
    ),
    SpyVwapTrendContinuationNormalToActiveRvolFilterStrategy.name: (
        SpyVwapTrendContinuationNormalToActiveRvolFilterStrategy
    ),
    SpyVwapTrendContinuationAtrDistanceFilterStrategy.name: (
        SpyVwapTrendContinuationAtrDistanceFilterStrategy
    ),
    SpyVwapTrendContinuationOpeningRangeConfluenceLooseFilterStrategy.name: (
        SpyVwapTrendContinuationOpeningRangeConfluenceLooseFilterStrategy
    ),
    SpyVwapTrendContinuationOpeningRangeConfluenceFilterStrategy.name: (
        SpyVwapTrendContinuationOpeningRangeConfluenceFilterStrategy
    ),
    SpyVwapTrendContinuationOpeningRangeConfluenceStrictFilterStrategy.name: (
        SpyVwapTrendContinuationOpeningRangeConfluenceStrictFilterStrategy
    ),
    SpyVwapTrendContinuationInitialStopStrategy.name: (SpyVwapTrendContinuationInitialStopStrategy),
    SpyVwapTrendContinuationOneRTargetStrategy.name: (SpyVwapTrendContinuationOneRTargetStrategy),
    SpyVwapTrendContinuationOneAndHalfRTargetStrategy.name: (
        SpyVwapTrendContinuationOneAndHalfRTargetStrategy
    ),
    SpyVwapTrendContinuationTwoRTargetStrategy.name: (SpyVwapTrendContinuationTwoRTargetStrategy),
    SpyVwapTrendContinuationBasicSignalQualityFilterStrategy.name: (
        SpyVwapTrendContinuationBasicSignalQualityFilterStrategy
    ),
    SpyVwapTrendContinuationStrongSignalQualityFilterStrategy.name: (
        SpyVwapTrendContinuationStrongSignalQualityFilterStrategy
    ),
    SpyVwapTrendContinuationSignalBreakEntryStrategy.name: (
        SpyVwapTrendContinuationSignalBreakEntryStrategy
    ),
    SpyVwapTrendContinuationSignalQualityBreakEntryStrategy.name: (
        SpyVwapTrendContinuationSignalQualityBreakEntryStrategy
    ),
    SpyVwapTrendContinuationTimeStopStrategy.name: (SpyVwapTrendContinuationTimeStopStrategy),
    SpyVwapTrendContinuationTimeStopThreeBarStrategy.name: (
        SpyVwapTrendContinuationTimeStopThreeBarStrategy
    ),
    SpyVwapTrendContinuationTimeStopSixBarStrategy.name: (
        SpyVwapTrendContinuationTimeStopSixBarStrategy
    ),
    SpyVwapTrendContinuationOneRTargetTimeStopStrategy.name: (
        SpyVwapTrendContinuationOneRTargetTimeStopStrategy
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
