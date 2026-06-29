"""Shared trading domain package."""

from trade_core.contracts import (
    DecisionAction,
    InstrumentRef,
    OrderIntent,
    OrderIntentId,
    OrderSide,
    OrderType,
    RiskDecision,
    RiskDecisionId,
    RiskOutcome,
    Signal,
    SignalDirection,
    SignalId,
    StrategyDecision,
    StrategyDecisionId,
    StrategyInputRef,
    StrategyRunId,
)

PACKAGE_NAME = "trade_core"

__all__ = [
    "DecisionAction",
    "InstrumentRef",
    "OrderIntent",
    "OrderIntentId",
    "OrderSide",
    "OrderType",
    "PACKAGE_NAME",
    "RiskDecision",
    "RiskDecisionId",
    "RiskOutcome",
    "Signal",
    "SignalDirection",
    "SignalId",
    "StrategyDecision",
    "StrategyDecisionId",
    "StrategyInputRef",
    "StrategyRunId",
]
