"""Liquidity / market-cap / penny filters applied before scoring."""
from __future__ import annotations

from dataclasses import dataclass

from src.config import get_config
from src.models.schemas import StockData
from src.utils.currency import to_sek


@dataclass
class FilterResult:
    data: StockData
    passed: bool
    reasons: list[str]


def _turnover_sek(data: StockData, fx: dict[str, float]) -> float | None:
    if not data.quote or data.quote.avg_turnover is None:
        return None
    return to_sek(data.quote.avg_turnover, data.currency, fx)


def evaluate(data: StockData, fx: dict[str, float], *, allow_small_cap: bool | None = None) -> FilterResult:
    cfg = get_config()
    reasons: list[str] = []
    if allow_small_cap is None:
        allow_small_cap = bool(cfg.get("filters.allow_small_cap", False))

    min_turnover = float(cfg.get("filters.min_avg_turnover_sek", 5_000_000))
    min_mcap = float(cfg.get("filters.min_market_cap_sek", 1_000_000_000))
    penny = float(cfg.get("filters.exclude_penny_below_local", 5.0))

    # penny
    if data.quote and data.quote.price < penny:
        reasons.append(f"Penny price < {penny:g} {data.currency}")

    # liquidity
    turn = _turnover_sek(data, fx)
    if turn is not None and turn < min_turnover:
        reasons.append(f"Low liquidity ({turn/1e6:.1f} MSEK/day < {min_turnover/1e6:.0f})")

    # market cap (skip if explicitly allowing small caps)
    if not allow_small_cap and data.quote and data.quote.market_cap is not None:
        mcap_sek = to_sek(data.quote.market_cap, data.currency, fx)
        if mcap_sek < min_mcap:
            reasons.append(f"Small cap ({mcap_sek/1e9:.2f} BSEK < {min_mcap/1e9:.1f})")

    return FilterResult(data=data, passed=len(reasons) == 0, reasons=reasons)


def apply_filters(items: list[StockData], fx: dict[str, float],
                  *, allow_small_cap: bool | None = None) -> tuple[list[StockData], list[FilterResult]]:
    """Return (passed_items, all_results)."""
    results = [evaluate(d, fx, allow_small_cap=allow_small_cap) for d in items]
    passed = [r.data for r in results if r.passed]
    return passed, results
