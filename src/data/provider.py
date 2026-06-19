"""Provider router + cache.

``get_stock_data`` is the single entry point the rest of the app uses. It:
  1. serves from the SQLite cache while fresh (TTL from config),
  2. tries real providers for the symbol's region in config order, merging
     coverage from multiple *real* sources (never mixing mock into real),
  3. enriches missing news via RSS,
  4. falls back to the deterministic mock provider when nothing real is
     available — clearly flagged ``is_mock=True``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.config import get_config
from src.data.base import DataProvider, merge_real, region_for_exchange
from src.data.borsdata_client import BorsdataClient
from src.data.eodhd_client import EodhdClient
from src.data.finnhub_client import FinnhubClient
from src.data.mock_provider import mock_provider
from src.data.yahoo_client import YahooClient, download_prices
from src.models.schemas import StockData
from src.storage.db import get_db
from src.utils.logging import get_logger

log = get_logger("provider")

_REAL: dict[str, DataProvider] = {
    "borsdata": BorsdataClient(),
    "eodhd": EodhdClient(),
    "finnhub": FinnhubClient(),
    "yahoo": YahooClient(),
}


def _providers_for_region(region: str) -> list[DataProvider]:
    cfg = get_config()
    order = cfg.get(f"data.providers.{region}", ["mock"])
    chosen: list[DataProvider] = []
    for name in order:
        prov = _REAL.get(name)
        if prov is not None and prov.available():
            chosen.append(prov)
    return chosen


def _cache_fresh(fetched_at: datetime) -> bool:
    ttl = float(get_config().get("data.cache_ttl_minutes", 60))
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    age_min = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 60.0
    return age_min < ttl


def _fetch_uncached(ticker: str, exchange: str, *, enrich_news: bool = True) -> StockData:
    """Provider loop + RSS enrich + mock fallback. NO DB access (thread-safe)."""
    cfg = get_config()
    symbol = f"{ticker}.{exchange}"
    region = region_for_exchange(exchange)

    data: StockData | None = None
    if cfg.allow_network and not cfg.get("data.force_mock", False):
        for prov in _providers_for_region(region):
            try:
                got = prov.fetch(ticker, exchange)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("%s failed for %s: %s", prov.name, symbol, exc)
                got = None
            if got is None:
                continue
            data = got if data is None else merge_real(data, got)
            if data.coverage.price and data.coverage.fundamentals:
                break

    if data is not None and data.coverage.price:
        if enrich_news and not data.news:
            try:
                from src.data.news_client import company_rss

                data.news = company_rss(ticker)
                data.coverage.news = bool(data.news)
            except Exception:  # pragma: no cover
                pass
        data.fetched_at = datetime.now(timezone.utc)
    else:
        data = mock_provider().fetch(ticker, exchange)
    return data


def get_stock_data(ticker: str, exchange: str, *, use_cache: bool = True,
                   force_refresh: bool = False, enrich_news: bool = True) -> StockData:
    db = get_db()
    if use_cache and not force_refresh:
        cached = db.cache_get(f"{ticker}.{exchange}")
        if cached and _cache_fresh(cached[1]):
            return cached[0]
    data = _fetch_uncached(ticker, exchange, enrich_news=enrich_news)
    db.cache_put(data)
    return data


def get_full_many(entries: list[tuple[str, str]], *, max_workers: int = 6,
                  force_refresh: bool = False) -> list[StockData]:
    """Full (fundamentals + analyst) fetch for many names, CONCURRENTLY.

    Cache reads/writes happen serially on the main thread (single shared SQLite
    connection); only the network fetches run in the thread pool.
    """
    from concurrent.futures import ThreadPoolExecutor

    db = get_db()
    results: dict[str, StockData] = {}
    misses: list[tuple[str, str]] = []
    for ticker, exchange in entries:
        sym = f"{ticker}.{exchange}"
        cached = None if force_refresh else db.cache_get(sym)
        if cached and _cache_fresh(cached[1]):
            results[sym] = cached[0]
        else:
            misses.append((ticker, exchange))

    if misses:
        def _job(e: tuple[str, str]):
            return e, _fetch_uncached(e[0], e[1], enrich_news=False)

        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            for (ticker, exchange), data in pool.map(_job, misses):
                results[f"{ticker}.{exchange}"] = data
                db.cache_put(data)  # serial write on main thread

    return [results[f"{t}.{e}"] for t, e in entries if f"{t}.{e}" in results]


def get_many(entries: list[tuple[str, str]], *, force_refresh: bool = False,
             enrich_news: bool = False) -> list[StockData]:
    """Fetch a list of (ticker, exchange) pairs (full per-name fetch)."""
    out: list[StockData] = []
    for ticker, exchange in entries:
        try:
            out.append(get_stock_data(ticker, exchange, force_refresh=force_refresh,
                                      enrich_news=enrich_news))
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("fetch failed %s.%s: %s", ticker, exchange, exc)
    return out


def _keyed_provider_available() -> bool:
    """True if any *keyed* real provider (not the keyless Yahoo) is usable."""
    return any(_REAL[n].available() for n in ("borsdata", "eodhd", "finnhub"))


def screen_data(entries: list[tuple[str, str]]) -> list[StockData]:
    """Data source for screening / backtest.

    When only the keyless Yahoo source is active, fetch prices in a single batch
    request (fast; fundamentals omitted -> shown as missing). When a keyed
    provider is configured, do full per-name fetches (rich fundamentals). Falls
    back to mock per-name when offline / forced.
    """
    cfg = get_config()
    if not cfg.allow_network or cfg.get("data.force_mock", False):
        return get_many(entries)
    if _keyed_provider_available():
        return get_many(entries)
    # keyless: Yahoo batch prices (fast), fall back to mock for any misses
    if _REAL["yahoo"].available():
        priced = download_prices(entries)
        out: list[StockData] = []
        for ticker, exchange in entries:
            sd = priced.get(f"{ticker}.{exchange}")
            out.append(sd if sd is not None else mock_provider().fetch(ticker, exchange))
        return out
    return get_many(entries)
