"""Market data ingestion and normalization boundaries."""

from trade_data.alpaca import AlpacaHistoricalBarsSource
from trade_data.models import (
    Bar,
    HistoricalBarsRequest,
    HistoricalBarsResult,
    HistoricalBarsSource,
    Instrument,
)
from trade_data.sessions import MarketSessionConfig
from trade_data.store import LocalMarketDataStore

PACKAGE_NAME = "trade_data"

__all__ = [
    "AlpacaHistoricalBarsSource",
    "Bar",
    "HistoricalBarsRequest",
    "HistoricalBarsResult",
    "HistoricalBarsSource",
    "Instrument",
    "LocalMarketDataStore",
    "MarketSessionConfig",
    "PACKAGE_NAME",
]
