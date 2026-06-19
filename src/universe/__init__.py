"""Screening universe loaders for Sweden, EU and US."""
from __future__ import annotations

from src.config import get_config
from src.universe.eu import EU
from src.universe.stockholm import STOCKHOLM
from src.universe.us import US

REGION_LISTS = {"nordic": STOCKHOLM, "eu": EU, "us": US}


def _parse_watchlist() -> list[tuple[str, str]]:
    """Parse config watchlist entries like 'VOLV-B.ST' -> ('VOLV-B','ST')."""
    out: list[tuple[str, str]] = []
    for item in get_config().get("universe.watchlist", []) or []:
        if "." in item:
            tkr, ex = item.rsplit(".", 1)
            out.append((tkr, ex))
    return out


def load_universe(region: str, *, include_watchlist: bool = True,
                  limit: int | None = None) -> list[tuple[str, str]]:
    cfg = get_config()
    if limit is None:
        limit = int(cfg.get(f"universe.limits.{region}", 60))
    base = list(REGION_LISTS.get(region, []))[:limit]
    if include_watchlist:
        for entry in _parse_watchlist():
            from src.data.base import region_for_exchange

            if region_for_exchange(entry[1]) == region and entry not in base:
                base.append(entry)
    return base


def load_screener_universe(region: str) -> list[tuple[str, str]]:
    """Curated, smaller set for the full-fundamentals live screener."""
    cfg = get_config()
    limit = int(cfg.get(f"universe.screener_limits.{region}",
                        cfg.get(f"universe.limits.{region}", 24)))
    return load_universe(region, limit=limit)


def load_all() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for region in ("nordic", "eu", "us"):
        out.extend(load_universe(region))
    return out
