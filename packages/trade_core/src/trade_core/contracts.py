"""Shared contracts at the strategy, risk, and order-intent boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Self
from uuid import uuid4


def ensure_utc(value: datetime) -> datetime:
    """Return an aware UTC datetime for durable trace records."""
    if value.tzinfo is None:
        msg = "datetime values must include timezone information"
        raise ValueError(msg)
    return value.astimezone(UTC)


def _new_id(prefix: str) -> str:
    normalized_prefix = "-".join(prefix.strip().lower().replace("_", "-").split())
    if not normalized_prefix:
        msg = "id prefix must not be empty"
        raise ValueError(msg)
    return f"{normalized_prefix}_{uuid4().hex}"


def _validated_id(value: str) -> str:
    normalized_value = value.strip()
    if not normalized_value:
        msg = "traceability id value must not be empty"
        raise ValueError(msg)
    return normalized_value


@dataclass(frozen=True, slots=True)
class StrategyRunId:
    """Identifier for one strategy evaluation or backtest/live decision run."""

    value: str

    @classmethod
    def new(cls, prefix: str = "strategy-run") -> Self:
        return cls(_new_id(prefix))

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _validated_id(self.value))


@dataclass(frozen=True, slots=True)
class StrategyDecisionId:
    """Identifier for one strategy-owned decision."""

    value: str

    @classmethod
    def new(cls, prefix: str = "strategy-decision") -> Self:
        return cls(_new_id(prefix))

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _validated_id(self.value))


@dataclass(frozen=True, slots=True)
class RiskDecisionId:
    """Identifier for one risk-policy decision about a strategy decision."""

    value: str

    @classmethod
    def new(cls, prefix: str = "risk-decision") -> Self:
        return cls(_new_id(prefix))

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _validated_id(self.value))


@dataclass(frozen=True, slots=True)
class OrderIntentId:
    """Identifier for one broker-neutral trade intent."""

    value: str

    @classmethod
    def new(cls, prefix: str = "order-intent") -> Self:
        return cls(_new_id(prefix))

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _validated_id(self.value))


@dataclass(frozen=True, slots=True)
class SignalId:
    """Identifier for an optional strategy signal that explains a decision."""

    value: str

    @classmethod
    def new(cls, prefix: str = "signal") -> Self:
        return cls(_new_id(prefix))

    def __post_init__(self) -> None:
        object.__setattr__(self, "value", _validated_id(self.value))


@dataclass(frozen=True, slots=True)
class InstrumentRef:
    """Project-owned instrument reference without provider or broker IDs."""

    instrument_id: str
    market: str
    currency: str

    def __post_init__(self) -> None:
        instrument_id = self.instrument_id.strip().upper()
        market = self.market.strip().upper()
        currency = self.currency.strip().upper()
        if not instrument_id:
            msg = "instrument_id must not be empty"
            raise ValueError(msg)
        if not market:
            msg = "market must not be empty"
            raise ValueError(msg)
        if not currency:
            msg = "currency must not be empty"
            raise ValueError(msg)
        object.__setattr__(self, "instrument_id", instrument_id)
        object.__setattr__(self, "market", market)
        object.__setattr__(self, "currency", currency)


@dataclass(frozen=True, slots=True)
class StrategyInputRef:
    """Reference to normalized input data used by a strategy decision."""

    instrument: InstrumentRef
    timeframe: str
    source: str
    observed_at_utc: datetime

    def __post_init__(self) -> None:
        timeframe = self.timeframe.strip()
        source = self.source.strip().lower()
        if not timeframe:
            msg = "timeframe must not be empty"
            raise ValueError(msg)
        if not source:
            msg = "source must not be empty"
            raise ValueError(msg)
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "observed_at_utc", ensure_utc(self.observed_at_utc))


class SignalDirection(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"


@dataclass(frozen=True, slots=True)
class Signal:
    """Optional shared signal record for strategies that expose signal state."""

    strategy_run_id: StrategyRunId
    instrument: InstrumentRef
    direction: SignalDirection
    reason: str
    generated_at_utc: datetime
    signal_id: SignalId = field(default_factory=SignalId.new)

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason:
            msg = "reason must not be empty"
            raise ValueError(msg)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "generated_at_utc", ensure_utc(self.generated_at_utc))


class DecisionAction(StrEnum):
    ENTER_LONG = "enter_long"
    EXIT_LONG = "exit_long"
    ENTER_SHORT = "enter_short"
    EXIT_SHORT = "exit_short"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class StrategyDecision:
    """Strategy output shared by backtesting and live execution."""

    strategy_run_id: StrategyRunId
    strategy_name: str
    action: DecisionAction
    input_refs: tuple[StrategyInputRef, ...]
    reason: str
    decided_at_utc: datetime
    signal_ids: tuple[SignalId, ...] = ()
    strategy_decision_id: StrategyDecisionId = field(default_factory=StrategyDecisionId.new)

    def __post_init__(self) -> None:
        strategy_name = self.strategy_name.strip()
        reason = self.reason.strip()
        if not strategy_name:
            msg = "strategy_name must not be empty"
            raise ValueError(msg)
        if not reason:
            msg = "reason must not be empty"
            raise ValueError(msg)
        object.__setattr__(self, "strategy_name", strategy_name)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "input_refs", tuple(self.input_refs))
        object.__setattr__(self, "signal_ids", tuple(self.signal_ids))
        object.__setattr__(self, "decided_at_utc", ensure_utc(self.decided_at_utc))


class RiskOutcome(StrEnum):
    APPROVED = "approved"
    MODIFIED = "modified"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class RiskDecision:
    """Risk-policy result for one strategy decision."""

    strategy_decision_id: StrategyDecisionId
    outcome: RiskOutcome
    reason: str
    decided_at_utc: datetime
    risk_decision_id: RiskDecisionId = field(default_factory=RiskDecisionId.new)

    @classmethod
    def approved(
        cls,
        *,
        strategy_decision_id: StrategyDecisionId,
        decided_at_utc: datetime,
        reason: str,
    ) -> Self:
        return cls(
            strategy_decision_id=strategy_decision_id,
            outcome=RiskOutcome.APPROVED,
            reason=reason,
            decided_at_utc=decided_at_utc,
        )

    @classmethod
    def rejected(
        cls,
        *,
        strategy_decision_id: StrategyDecisionId,
        decided_at_utc: datetime,
        reason: str,
    ) -> Self:
        return cls(
            strategy_decision_id=strategy_decision_id,
            outcome=RiskOutcome.REJECTED,
            reason=reason,
            decided_at_utc=decided_at_utc,
        )

    @classmethod
    def modified(
        cls,
        *,
        strategy_decision_id: StrategyDecisionId,
        decided_at_utc: datetime,
        reason: str,
    ) -> Self:
        return cls(
            strategy_decision_id=strategy_decision_id,
            outcome=RiskOutcome.MODIFIED,
            reason=reason,
            decided_at_utc=decided_at_utc,
        )

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason:
            msg = "reason must not be empty"
            raise ValueError(msg)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "decided_at_utc", ensure_utc(self.decided_at_utc))


class OrderSide(StrEnum):
    BUY = "buy"
    SELL = "sell"


class OrderType(StrEnum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_MARKET = "stop_market"
    STOP_LIMIT = "stop_limit"


@dataclass(frozen=True, slots=True)
class OrderIntent:
    """Broker-neutral trade intent produced after a risk decision."""

    strategy_decision_id: StrategyDecisionId
    risk_decision_id: RiskDecisionId
    instrument: InstrumentRef
    side: OrderSide
    quantity: Decimal
    order_type: OrderType
    created_at_utc: datetime
    reason: str
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None
    time_in_force: str = "DAY"
    order_intent_id: OrderIntentId = field(default_factory=OrderIntentId.new)

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        time_in_force = self.time_in_force.strip().upper()
        if self.quantity <= 0:
            msg = "quantity must be positive"
            raise ValueError(msg)
        if not reason:
            msg = "reason must not be empty"
            raise ValueError(msg)
        if not time_in_force:
            msg = "time_in_force must not be empty"
            raise ValueError(msg)
        if self.limit_price is not None and self.limit_price <= 0:
            msg = "limit_price must be positive when provided"
            raise ValueError(msg)
        if self.stop_price is not None and self.stop_price <= 0:
            msg = "stop_price must be positive when provided"
            raise ValueError(msg)
        if self.order_type in {OrderType.LIMIT, OrderType.STOP_LIMIT} and self.limit_price is None:
            msg = "limit_price is required for limit order intents"
            raise ValueError(msg)
        stop_order_types = {OrderType.STOP_MARKET, OrderType.STOP_LIMIT}
        if self.order_type in stop_order_types and self.stop_price is None:
            msg = "stop_price is required for stop order intents"
            raise ValueError(msg)
        if self.order_type == OrderType.MARKET and (
            self.limit_price is not None or self.stop_price is not None
        ):
            msg = "market order intents must not include limit_price or stop_price"
            raise ValueError(msg)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "time_in_force", time_in_force)
        object.__setattr__(self, "created_at_utc", ensure_utc(self.created_at_utc))
