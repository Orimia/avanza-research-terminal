"""EODHD client (global US/EU fundamentals, prices, news).

Docs: https://eodhd.com/financial-apis/  (token via ``api_token``)
Returns ``None`` on any failure so the router can fall back.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.config import get_config
from src.data.base import DataProvider
from src.models.schemas import (
    Fundamentals,
    NewsItem,
    PriceBar,
    Quote,
    SourceCoverage,
    StockData,
)
from src.utils.logging import get_logger, log_network_call

log = get_logger("eodhd")
BASE = "https://eodhd.com/api"

# Map our exchange codes to EODHD suffixes.
_SUFFIX = {
    "US": "US", "NYSE": "US", "NASDAQ": "US",
    "ST": "ST", "STO": "ST",
    "EU": "XETRA", "XETRA": "XETRA", "PAR": "PA", "AMS": "AS", "MIL": "MI",
    "CO": "CO", "HE": "HE", "OL": "OL",
}


class EodhdClient(DataProvider):
    name = "eodhd"

    def __init__(self) -> None:
        self.cfg = get_config()
        self.key = self.cfg.env("EODHD_API_KEY")

    def available(self) -> bool:
        return bool(self.key) and self.cfg.allow_network

    def _symbol(self, ticker: str, exchange: str) -> str:
        suffix = _SUFFIX.get((exchange or "").upper(), "US")
        return f"{ticker}.{suffix}"

    def _get(self, path: str, params: dict | None = None):
        import httpx

        params = dict(params or {})
        params.update({"api_token": self.key, "fmt": "json"})
        url = f"{BASE}{path}"
        safe = url + "?api_token=***"
        try:
            log_network_call(self.name, safe, note="request")
            resp = httpx.get(url, params=params, timeout=15.0)
            log_network_call(self.name, safe, status=resp.status_code)
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as exc:  # pragma: no cover - network
            log.warning("EODHD request failed: %s", exc)
            return None

    def fetch(self, ticker: str, exchange: str) -> Optional[StockData]:
        if not self.available():
            return None
        sym = self._symbol(ticker, exchange)
        eod = self._get(f"/eod/{sym}", {"period": "d", "order": "a"})
        bars: list[PriceBar] = []
        for row in eod or []:
            try:
                bars.append(PriceBar(
                    date=datetime.fromisoformat(row["date"]).date(),
                    open=float(row["open"]), high=float(row["high"]),
                    low=float(row["low"]), close=float(row.get("adjusted_close", row["close"])),
                    volume=float(row.get("volume", 0) or 0),
                ))
            except Exception:
                continue
        bars = bars[-400:]
        if not bars:
            return None
        last = bars[-1]

        fund_raw = self._get(f"/fundamentals/{sym}") or {}
        fundamentals, name, sector, ccy, mcap = self._parse_fundamentals(fund_raw)
        news = self._news(sym)

        quote = Quote(
            price=last.close, currency=ccy or "USD", market_cap=mcap,
            volume=last.volume,
            avg_volume=sum(b.volume for b in bars[-20:]) / max(1, len(bars[-20:])),
            avg_turnover=sum(b.volume * b.close for b in bars[-20:]) / max(1, len(bars[-20:])),
            as_of=datetime.now(timezone.utc),
        )
        return StockData(
            ticker=ticker, exchange=exchange, name=name, sector=sector,
            currency=ccy or "USD", quote=quote, fundamentals=fundamentals,
            price_history=bars, news=news, catalysts=None, sources=["eodhd"],
            coverage=SourceCoverage(provider="eodhd", price=True,
                                    fundamentals=fundamentals is not None,
                                    news=bool(news), catalysts=False, is_mock=False),
            is_mock=False, fetched_at=datetime.now(timezone.utc),
        )

    def _parse_fundamentals(self, raw: dict):
        if not raw:
            return None, None, None, None, None
        general = raw.get("General", {}) or {}
        high = raw.get("Highlights", {}) or {}
        val = raw.get("Valuation", {}) or {}
        name = general.get("Name")
        sector = general.get("Sector")
        ccy = general.get("CurrencyCode")
        mcap = high.get("MarketCapitalization")

        def f(d, k):
            v = d.get(k)
            try:
                return float(v) if v not in (None, "", "NA") else None
            except (TypeError, ValueError):
                return None

        fundamentals = Fundamentals(
            revenue_growth=f(high, "QuarterlyRevenueGrowthYOY"),
            eps_growth=f(high, "QuarterlyEarningsGrowthYOY"),
            gross_margin=f(high, "GrossMargin") if high.get("GrossMargin") else None,
            operating_margin=f(high, "OperatingMarginTTM"),
            net_margin=f(high, "ProfitMargin"),
            roic=None, roe=f(high, "ReturnOnEquityTTM"),
            pe=f(high, "PERatio"), forward_pe=f(val, "ForwardPE"),
            ev_ebitda=f(val, "EnterpriseValueEbitda"),
            ev_sales=f(val, "EnterpriseValueRevenue"),
            ps=f(val, "PriceSalesTTM"), pb=f(val, "PriceBookMRQ"),
            dividend_yield=f(high, "DividendYield"),
            as_of=None,
        )
        return fundamentals, name, sector, ccy, (float(mcap) if mcap else None)

    def _news(self, sym: str) -> list[NewsItem]:
        rows = self._get("/news", {"s": sym, "limit": 8}) or []
        out: list[NewsItem] = []
        for r in rows:
            try:
                out.append(NewsItem(
                    title=r["title"], url=r["link"], source="EODHD",
                    timestamp=datetime.fromisoformat(r["date"].replace("Z", "+00:00")),
                    summary=(r.get("content") or "")[:280] or None,
                    sentiment=(r.get("sentiment") or {}).get("polarity"),
                ))
            except Exception:
                continue
        return out
