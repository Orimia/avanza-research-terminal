"""Börsdata API client (primary Nordic source).

Docs: https://github.com/Borsdata-Sweden/API  (base: apiservice.borsdata.se/v1)
Auth is via the ``authKey`` query parameter (BORSDATA_API_KEY).

Conservative by design: it fetches prices and annual reports (real, well-defined
fields) and derives margins / growth from them. Ratios it cannot derive reliably
(e.g. EV/EBITDA) are left as ``None`` rather than guessed. Any error -> ``None``
so the router falls back to mock.

NOTE: instrument field names and report keys should be verified against your live
API response; parsing is defensive and skips unknown shapes.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from src.config import get_config
from src.data.base import DataProvider
from src.models.schemas import (
    Fundamentals,
    PriceBar,
    Quote,
    SourceCoverage,
    StockData,
)
from src.utils.logging import get_logger, log_network_call

log = get_logger("borsdata")
BASE = "https://apiservice.borsdata.se/v1"


class BorsdataClient(DataProvider):
    name = "borsdata"

    def __init__(self) -> None:
        self.cfg = get_config()
        self.key = self.cfg.env("BORSDATA_API_KEY")
        self._instruments_cache: dict[str, dict] | None = None

    def available(self) -> bool:
        return bool(self.key) and self.cfg.allow_network

    # -- helpers -----------------------------------------------------------
    def _get(self, path: str, params: dict | None = None) -> Optional[dict]:
        import httpx

        params = dict(params or {})
        params["authKey"] = self.key
        url = f"{BASE}{path}"
        safe = url + "?authKey=***"
        try:
            log_network_call(self.name, safe, note="request")
            resp = httpx.get(url, params=params, timeout=15.0)
            log_network_call(self.name, safe, status=resp.status_code)
            if resp.status_code != 200:
                return None
            return resp.json()
        except Exception as exc:  # pragma: no cover - network
            log.warning("Börsdata request failed: %s", exc)
            return None

    def _instruments(self) -> dict[str, dict]:
        # memoise on the instance (avoids lru_cache-on-method self-leak)
        if self._instruments_cache is None:
            data = self._get("/instruments") or {}
            out: dict[str, dict] = {}
            for ins in data.get("instruments", []) or []:
                tkr = str(ins.get("ticker", "")).upper().replace(" ", "-")
                if tkr:
                    out[tkr] = ins
            self._instruments_cache = out
        return self._instruments_cache

    def _find(self, ticker: str) -> Optional[dict]:
        key = ticker.upper().replace(" ", "-")
        ins = self._instruments()
        return ins.get(key) or ins.get(key.replace("-", " "))

    # -- main --------------------------------------------------------------
    def fetch(self, ticker: str, exchange: str) -> Optional[StockData]:
        if not self.available():
            return None
        ins = self._find(ticker)
        if not ins:
            return None
        ins_id = ins.get("insId")
        if ins_id is None:
            return None

        prices = self._get(f"/instruments/{ins_id}/stockprices", {"maxCount": 400})
        bars: list[PriceBar] = []
        for p in (prices or {}).get("stockPricesList", []) or []:
            try:
                bars.append(PriceBar(
                    date=datetime.fromisoformat(p["d"]).date(),
                    open=float(p.get("o", p["c"])), high=float(p.get("h", p["c"])),
                    low=float(p.get("l", p["c"])), close=float(p["c"]),
                    volume=float(p.get("v", 0) or 0),
                ))
            except Exception:
                continue
        bars.sort(key=lambda b: b.date)
        if not bars:
            return None

        last = bars[-1]
        quote = Quote(price=last.close, currency="SEK",
                      volume=last.volume,
                      avg_volume=sum(b.volume for b in bars[-20:]) / max(1, len(bars[-20:])),
                      avg_turnover=(sum(b.volume * b.close for b in bars[-20:])
                                    / max(1, len(bars[-20:]))),
                      as_of=datetime.now(timezone.utc))

        fundamentals = self._fundamentals(ins_id, last.close)

        return StockData(
            ticker=ticker, exchange=exchange,
            name=ins.get("name"), sector=str(ins.get("sectorId", "")) or None,
            country="Sweden", currency="SEK",
            quote=quote, fundamentals=fundamentals, price_history=bars,
            news=[], catalysts=None, sources=["borsdata"],
            coverage=SourceCoverage(provider="borsdata", price=True,
                                    fundamentals=fundamentals is not None,
                                    news=False, catalysts=False, is_mock=False),
            is_mock=False, fetched_at=datetime.now(timezone.utc),
        )

    def _fundamentals(self, ins_id: int, price: float) -> Optional[Fundamentals]:
        reports = self._get(f"/instruments/{ins_id}/reports/year", {"maxCount": 2})
        rows = (reports or {}).get("reports", []) or []
        if not rows:
            return None
        cur = rows[0]
        prev = rows[1] if len(rows) > 1 else None

        def g(row, key):
            v = row.get(key) if row else None
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        rev = g(cur, "revenues")
        rev_prev = g(prev, "revenues") if prev else None
        eps = g(cur, "earnings_Per_Share")
        eps_prev = g(prev, "earnings_Per_Share") if prev else None
        gross = g(cur, "gross_Income")
        op = g(cur, "operating_Income")
        net = g(cur, "profit_To_Equity_Holders")

        def safe_div(a, b):
            return (a / b) if (a is not None and b not in (None, 0)) else None

        def growth(a, b):
            return ((a - b) / abs(b)) if (a is not None and b not in (None, 0)) else None

        return Fundamentals(
            revenue_growth=growth(rev, rev_prev),
            eps_growth=growth(eps, eps_prev),
            gross_margin=safe_div(gross, rev),
            operating_margin=safe_div(op, rev),
            net_margin=safe_div(net, rev),
            fcf=g(cur, "free_Cash_Flow"),
            pe=safe_div(price, eps),
            as_of=None,
        )
