"""OpenBB Platform provider — multi-source, normalized real data.

OpenBB (github.com/OpenBB-finance/OpenBB) aggregates dozens of financial data
providers behind one standardized API. Here it joins the provider chain as
*redundancy + enrichment*: keyless by default (its bundled yfinance source),
and it automatically upgrades if the user adds provider keys through OpenBB's
own credential store — no code changes here.

Same contract as every provider in this codebase: return ``None`` when a
symbol can't be served, keep missing fields ``None``, never invent data.
The import is heavy (~seconds), so it is deferred until first use;
``available()`` only checks that the package exists.
"""
from __future__ import annotations

import importlib.util
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from src.config import get_config
from src.data.base import DataProvider
from src.data.yahoo_client import yahoo_symbol
from src.models.schemas import (
    AnalystView,
    Fundamentals,
    NewsItem,
    PriceBar,
    Quote,
    SourceCoverage,
    StockData,
)
from src.utils.currency import currency_for_exchange
from src.utils.logging import get_logger, log_network_call

log = get_logger("openbb")

_OBB: Any = None          # cached heavy import


def _get_obb():
    global _OBB
    if _OBB is None:
        from openbb import obb  # heavy: several seconds on first import

        _OBB = obb
    return _OBB


def _g(obj: Any, *names: str) -> Any:
    """First non-None attribute among ``names`` (tolerates schema drift)."""
    for n in names:
        v = getattr(obj, n, None)
        if v is not None:
            return v
    return None


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    return f if f == f else None


def _first(results: Any) -> Any:
    if isinstance(results, list):
        return results[0] if results else None
    return results


# -- pure mappers (unit-tested offline) ------------------------------------- #
def bars_from_results(results: list) -> list[PriceBar]:
    bars: list[PriceBar] = []
    for r in results or []:
        d = _g(r, "date")
        c = _num(_g(r, "close"))
        if d is None or c is None or c <= 0:
            continue
        if isinstance(d, datetime):
            d = d.date()
        bars.append(PriceBar(
            date=d, close=c,
            open=_num(_g(r, "open")) or c, high=_num(_g(r, "high")) or c,
            low=_num(_g(r, "low")) or c, volume=_num(_g(r, "volume")) or 0.0,
        ))
    return bars


def fundamentals_from(m: Any) -> Optional[Fundamentals]:
    if m is None:
        return None
    # OpenBB's yfinance source reports dividend_yield in PERCENT (verified against
    # live large-cap payers; same upstream quirk as the yahoo_client 100x bug),
    # so ALWAYS convert; a >1 guard would corrupt sub-1% payers (e.g. 0.23 = 0.23%).
    divy = _num(_g(m, "dividend_yield", "dividend_yield_ttm"))
    if divy is not None:
        divy = divy / 100.0
    f = Fundamentals(
        revenue_growth=_num(_g(m, "revenue_growth", "revenue_growth_ttm")),
        eps_growth=_num(_g(m, "earnings_growth", "eps_growth")),
        gross_margin=_num(_g(m, "gross_margin")),
        operating_margin=_num(_g(m, "operating_margin")),
        net_margin=_num(_g(m, "profit_margin", "net_margin")),
        roe=_num(_g(m, "return_on_equity", "roe")),
        pe=_num(_g(m, "pe_ratio", "trailing_pe", "pe")),
        forward_pe=_num(_g(m, "forward_pe")),
        ev_ebitda=_num(_g(m, "enterprise_to_ebitda", "ev_to_ebitda")),
        ev_sales=_num(_g(m, "enterprise_to_revenue", "ev_to_sales")),
        ps=_num(_g(m, "price_to_sales", "ps_ratio")),
        pb=_num(_g(m, "price_to_book", "pb_ratio")),
        dividend_yield=divy,
    )
    return f if f.available_fields() > 0 else None


def analyst_from(c: Any) -> Optional[AnalystView]:
    if c is None:
        return None
    target = _num(_g(c, "target_consensus", "target_mean", "target_median"))
    rec = _g(c, "recommendation", "rating")
    if target is None and rec is None:
        return None
    n = _g(c, "target_number_of_analysts", "number_of_analysts", "analyst_count")
    return AnalystView(
        target_mean=target,
        target_high=_num(_g(c, "target_high")),
        target_low=_num(_g(c, "target_low")),
        n_analysts=int(n) if isinstance(n, (int, float)) else None,
        recommendation=str(rec).lower() if isinstance(rec, str) else None,
        recommendation_mean=_num(_g(c, "recommendation_mean")),
    )


# -- provider ---------------------------------------------------------------- #
class OpenBBClient(DataProvider):
    name = "openbb"

    def available(self) -> bool:
        if not get_config().allow_network:
            return False
        return importlib.util.find_spec("openbb") is not None   # cheap check

    def fetch(self, ticker: str, exchange: str) -> Optional[StockData]:
        if not self.available():
            return None
        sym = yahoo_symbol(ticker, exchange)   # OpenBB's yfinance source uses Yahoo symbology
        if not sym:
            return None
        try:
            obb = _get_obb()
        except Exception as exc:  # pragma: no cover - import failure
            log.warning("openbb import failed: %s", exc)
            return None

        start = (date.today() - timedelta(days=int(
            get_config().get("data.price_history_days", 400) * 1.6))).isoformat()
        try:
            log_network_call(self.name, f"openbb://equity.price.historical/{sym}")
            hist = obb.equity.price.historical(symbol=sym, start_date=start,
                                               provider="yfinance")
            bars = bars_from_results(hist.results)
        except Exception as exc:
            log.info("openbb historical failed for %s: %s", sym, exc)
            return None
        if not bars:
            return None

        name = sector = country = description = None
        fundamentals = analyst = None
        market_cap = None
        try:
            log_network_call(self.name, f"openbb://equity.profile/{sym}")
            p = _first(obb.equity.profile(symbol=sym, provider="yfinance").results)
            if p is not None:
                name = _g(p, "name", "long_name", "short_name")
                sector = _g(p, "sector")
                country = _g(p, "country", "hq_country")
                description = _g(p, "long_description", "description")
        except Exception:
            pass
        try:
            log_network_call(self.name, f"openbb://equity.fundamental.metrics/{sym}")
            m = _first(obb.equity.fundamental.metrics(symbol=sym, provider="yfinance").results)
            fundamentals = fundamentals_from(m)
            market_cap = _num(_g(m, "market_cap")) if m is not None else None
        except Exception:
            pass
        try:
            log_network_call(self.name, f"openbb://equity.estimates.consensus/{sym}")
            c = _first(obb.equity.estimates.consensus(symbol=sym, provider="yfinance").results)
            analyst = analyst_from(c)
        except Exception:
            pass

        ccy = currency_for_exchange(exchange)
        last = bars[-1]
        recent = bars[-20:]
        avg_vol = sum(b.volume for b in recent) / max(1, len(recent))
        return StockData(
            ticker=ticker, exchange=exchange, name=name or ticker,
            sector=sector, country=country, currency=ccy,
            description=description if isinstance(description, str) else None,
            quote=Quote(price=last.close, currency=ccy, market_cap=market_cap,
                        volume=last.volume, avg_volume=avg_vol,
                        avg_turnover=avg_vol * last.close,
                        as_of=datetime.now(timezone.utc)),
            fundamentals=fundamentals, price_history=bars, news=[],
            catalysts=None, analyst=analyst, sources=["openbb"],
            coverage=SourceCoverage(provider="openbb", price=True,
                                    fundamentals=fundamentals is not None,
                                    news=False, catalysts=False, is_mock=False),
            is_mock=False, fetched_at=datetime.now(timezone.utc),
        )


def company_news(ticker: str, exchange: str, limit: int = 8) -> list[NewsItem]:
    """News enrichment via OpenBB (keyless yfinance source). Best-effort."""
    client = OpenBBClient()
    if not client.available():
        return []
    sym = yahoo_symbol(ticker, exchange)
    if not sym:
        return []
    try:
        obb = _get_obb()
        log_network_call("openbb", f"openbb://news.company/{sym}")
        res = obb.news.company(symbol=sym, provider="yfinance", limit=limit).results
    except Exception:
        return []
    out: list[NewsItem] = []
    for r in res or []:
        title, url = _g(r, "title"), _g(r, "url", "link")
        ts = _g(r, "date", "published")
        if not (title and url):
            continue
        if isinstance(ts, date) and not isinstance(ts, datetime):
            ts = datetime(ts.year, ts.month, ts.day, tzinfo=timezone.utc)
        out.append(NewsItem(title=str(title), url=str(url),
                            source=str(_g(r, "source", "provider") or "OpenBB"),
                            timestamp=ts or datetime.now(timezone.utc)))
    return out[:limit]
