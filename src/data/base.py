"""Provider interface and region helpers.

Every concrete data source implements :class:`DataProvider`. Real providers
return ``None`` when they cannot serve a symbol (missing key, network off, HTTP
error, or symbol not covered). They must NEVER fabricate values to fill gaps —
missing fields stay ``None`` so the rest of the system can mark them missing.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from src.models.schemas import StockData

_NORDIC = {"ST", "STO", "OMX", "CO", "HE", "OL"}
_US = {"US", "NYSE", "NASDAQ", "NMS"}
_CRYPTO = {"CC", "CRYPTO"}


def region_for_exchange(exchange: str) -> str:
    ex = (exchange or "").upper()
    if ex in _NORDIC:
        return "nordic"
    if ex in _US:
        return "us"
    if ex in _CRYPTO:
        return "crypto"
    return "eu"


def merge_real(base: StockData, other: StockData) -> StockData:
    """Fill ``None``/empty fields in ``base`` from ``other`` (both real sources).

    Used to combine coverage from two real providers (e.g. one has prices, the
    other has fundamentals). Never used to merge mock into real.
    """
    if base.quote is None:
        base.quote = other.quote
    if base.fundamentals is None:
        base.fundamentals = other.fundamentals
    if not base.price_history:
        base.price_history = other.price_history
    if not base.news:
        base.news = other.news
    if base.catalysts is None:
        base.catalysts = other.catalysts
    base.name = base.name or other.name
    base.sector = base.sector or other.sector
    base.country = base.country or other.country
    for s in other.sources:
        if s not in base.sources:
            base.sources.append(s)
    # refresh coverage flags ("price" == has a current quote; history is
    # reflected separately by the chart/backtest availability)
    base.coverage.price = base.quote is not None
    base.coverage.fundamentals = base.fundamentals is not None
    base.coverage.news = bool(base.news)
    base.coverage.catalysts = base.catalysts is not None
    return base


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def available(self) -> bool:
        """True if this provider can be used (key present, network allowed)."""

    @abstractmethod
    def fetch(self, ticker: str, exchange: str) -> Optional[StockData]:
        """Return a :class:`StockData` or ``None`` if it cannot serve it."""
