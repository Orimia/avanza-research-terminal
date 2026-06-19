"""Finnhub client (US/EU quote, fundamentals metrics, news, earnings).

Docs: https://finnhub.io/docs/api  (token via ``token``)
Historical candles are a premium endpoint and are intentionally NOT relied upon;
this client supplies quote, fundamentals metrics, company profile, news and the
next earnings date. Price history comes from EODHD/Börsdata. Errors -> ``None``.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

from src.config import get_config
from src.data.base import DataProvider
from src.models.schemas import (
    Catalysts,
    Fundamentals,
    NewsItem,
    Quote,
    SourceCoverage,
    StockData,
)
from src.utils.logging import get_logger, log_network_call

log = get_logger("finnhub")
BASE = "https://finnhub.io/api/v1"


class FinnhubClient(DataProvider):
    name = "finnhub"

    def __init__(self) -> None:
        self.cfg = get_config()
        self.key = self.cfg.env("FINNHUB_API_KEY")

    def available(self) -> bool:
        return bool(self.key) and self.cfg.allow_network

    def _get(self, path: str, params: dict | None = None):
        import httpx

        params = dict(params or {})
        params["token"] = self.key
        url = f"{BASE}{path}"
        safe = url + "?token=***"
        try:
            log_network_call(self.name, safe, note="request")
            resp = httpx.get(url, params=params, timeout=12.0)
            log_network_call(self.name, safe, status=resp.status_code)
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as exc:  # pragma: no cover - network
            log.warning("Finnhub request failed: %s", exc)
            return None

    def fetch(self, ticker: str, exchange: str) -> Optional[StockData]:
        if not self.available():
            return None
        sym = ticker  # Finnhub uses bare US symbols; EU needs venue suffixes
        quote_raw = self._get("/quote", {"symbol": sym})
        if not quote_raw or not quote_raw.get("c"):
            return None
        profile = self._get("/stock/profile2", {"symbol": sym}) or {}
        metric = (self._get("/stock/metric", {"symbol": sym, "metric": "all"}) or {}).get("metric", {})

        price = float(quote_raw["c"])
        ccy = profile.get("currency", "USD")

        def m(k):
            v = metric.get(k)
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        def pct(k):
            """Finnhub returns margins/growth/yields as percent numbers
            (e.g. 45.2 for 45.2%); the scoring engine expects fractions."""
            v = m(k)
            return v / 100.0 if v is not None else None

        # 10DayAverageTradingVolume is reported in millions of shares.
        adv_m = m("10DayAverageTradingVolume")
        avg_volume = adv_m * 1e6 if adv_m is not None else None
        quote = Quote(price=price, currency=ccy,
                      market_cap=(float(profile["marketCapitalization"]) * 1e6
                                  if profile.get("marketCapitalization") else None),
                      volume=None, avg_volume=avg_volume,
                      avg_turnover=(avg_volume * price) if avg_volume else None,
                      as_of=datetime.now(timezone.utc))

        fundamentals = Fundamentals(
            revenue_growth=pct("revenueGrowthTTMYoy"),
            eps_growth=pct("epsGrowthTTMYoy"),
            gross_margin=pct("grossMarginTTM"),
            operating_margin=pct("operatingMarginTTM"),
            net_margin=pct("netProfitMarginTTM"),
            roe=pct("roeTTM"), roic=pct("roiTTM"),
            # Finnhub's free metrics have no clean net-debt/EBITDA or EV/EBITDA;
            # leave them missing rather than substitute a different ratio.
            net_debt_ebitda=None,
            pe=m("peTTM"), ps=m("psTTM"), pb=m("pbQuarterly"),
            ev_ebitda=None,
            dividend_yield=pct("dividendYieldIndicatedAnnual"),
            as_of=None,
        )

        catalysts = self._catalysts(sym)
        news = self._news(sym)

        return StockData(
            ticker=ticker, exchange=exchange, name=profile.get("name"),
            sector=profile.get("finnhubIndustry"), country=profile.get("country"),
            currency=ccy, quote=quote, fundamentals=fundamentals,
            price_history=[], news=news, catalysts=catalysts, sources=["finnhub"],
            coverage=SourceCoverage(provider="finnhub", price=True,
                                    fundamentals=True, news=bool(news),
                                    catalysts=catalysts is not None, is_mock=False),
            is_mock=False, fetched_at=datetime.now(timezone.utc),
        )

    def _catalysts(self, sym: str) -> Optional[Catalysts]:
        today = date.today()
        cal = self._get("/calendar/earnings",
                        {"symbol": sym, "from": today.isoformat(),
                         "to": (today + timedelta(days=120)).isoformat()})
        rows = (cal or {}).get("earningsCalendar", []) or []
        if not rows:
            return None
        try:
            nxt = date.fromisoformat(rows[0]["date"])
            return Catalysts(next_earnings_date=nxt, days_to_earnings=(nxt - today).days)
        except Exception:
            return None

    def _news(self, sym: str) -> list[NewsItem]:
        today = date.today()
        rows = self._get("/company-news",
                         {"symbol": sym, "from": (today - timedelta(days=21)).isoformat(),
                          "to": today.isoformat()}) or []
        out: list[NewsItem] = []
        for r in rows[:8]:
            try:
                out.append(NewsItem(
                    title=r["headline"], url=r["url"], source=r.get("source", "Finnhub"),
                    timestamp=datetime.fromtimestamp(r["datetime"], tz=timezone.utc),
                    summary=(r.get("summary") or "")[:280] or None,
                ))
            except Exception:
                continue
        return out
