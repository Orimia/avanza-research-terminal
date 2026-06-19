"""Deterministic mock data provider.

Generates realistic, *stable-per-symbol* data so the entire terminal works with
no API keys. A latent "quality" factor per symbol keeps each company internally
coherent (a high-quality name has better margins, growth, momentum and a richer
valuation) so scores and recommendations are meaningful rather than random noise.

All mock output is flagged ``is_mock=True`` and uses obviously-fake news URLs
(``news.mock.local``) so it can never be mistaken for a real citation.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.config import get_config
from src.data.base import DataProvider
from src.models.schemas import (
    Catalysts,
    Fundamentals,
    NewsItem,
    PriceBar,
    Quote,
    SourceCoverage,
    StockData,
)
from src.utils.currency import currency_for_exchange

_SECTORS = [
    "Technology", "Healthcare", "Financials", "Industrials", "Energy",
    "Consumer", "Materials", "Communication", "Utilities", "Real Estate",
]
_COUNTRY = {"nordic": "Sweden", "us": "United States", "eu": "Germany"}
_HEADLINES = [
    "{name} reports quarterly results, {dir} guidance",
    "{name} wins major contract in core segment",
    "Analysts adjust price targets on {name} after results",
    "{name} announces buyback programme",
    "{name} faces margin pressure from input costs",
    "{name} expands into new markets",
    "Insider transactions disclosed at {name}",
    "{name} management reiterates full-year outlook",
]


def _seed(symbol: str) -> int:
    h = hashlib.sha256(symbol.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def _region(exchange: str) -> str:
    from src.data.base import region_for_exchange

    return region_for_exchange(exchange)


class MockProvider(DataProvider):
    name = "mock"

    def available(self) -> bool:
        return True

    def fetch(self, ticker: str, exchange: str) -> StockData:
        symbol = f"{ticker}.{exchange}"
        rng = np.random.default_rng(_seed(symbol))
        q = float(rng.beta(2.2, 2.2))  # latent quality 0..1, centred
        region = _region(exchange)
        ccy = currency_for_exchange(exchange)

        sector = _SECTORS[rng.integers(0, len(_SECTORS))]
        days = int(get_config().get("data.price_history_days", 400))

        history, last_close = self._price_history(rng, q, days)
        quote = self._quote(rng, q, last_close, ccy)
        fundamentals = self._fundamentals(rng, q)
        catalysts = self._catalysts(rng, q)
        news = self._news(rng, ticker, q)

        return StockData(
            ticker=ticker,
            exchange=exchange,
            name=f"{ticker.replace('-', ' ').title()} (mock)",
            sector=sector,
            country=_COUNTRY.get(region, "Europe"),
            currency=ccy,
            quote=quote,
            fundamentals=fundamentals,
            price_history=history,
            news=news,
            catalysts=catalysts,
            sources=["mock"],
            coverage=SourceCoverage(
                provider="mock", price=True, fundamentals=True,
                news=True, catalysts=True, is_mock=True,
            ),
            is_mock=True,
            fetched_at=datetime.now(timezone.utc),
        )

    # -- components --------------------------------------------------------
    def _price_history(self, rng, q: float, days: int) -> tuple[list[PriceBar], float]:
        p0 = float(rng.uniform(25, 900))
        mu = (q - 0.45) * 0.45               # annual drift, quality-linked
        sigma = 0.18 + (1.0 - q) * 0.45      # annual vol, worse quality = noisier
        dt = 1.0 / 252.0
        shocks = rng.normal(mu * dt, sigma * np.sqrt(dt), days)
        path = p0 * np.exp(np.cumsum(shocks))
        dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
        base_vol = float(rng.uniform(2e5, 5e6))
        bars: list[PriceBar] = []
        for i, d in enumerate(dates):
            close = float(path[i])
            intraday = abs(rng.normal(0, sigma * np.sqrt(dt))) * close
            high = close + abs(rng.normal(0, 0.4)) * intraday + 0.002 * close
            low = close - abs(rng.normal(0, 0.4)) * intraday - 0.002 * close
            open_ = float(np.clip(rng.normal(close, intraday), low, high))
            spike = 3.0 if rng.random() < 0.03 else 1.0
            vol = max(1.0, base_vol * float(rng.lognormal(0, 0.35)) * spike)
            bars.append(PriceBar(
                date=d.date(), open=round(open_, 2), high=round(max(high, open_, close), 2),
                low=round(min(low, open_, close), 2), close=round(close, 2), volume=round(vol),
            ))
        return bars, float(path[-1])

    def _quote(self, rng, q: float, last_close: float, ccy: str) -> Quote:
        shares_out = float(rng.uniform(8e7, 2.5e9))
        avg_volume = float(rng.uniform(1e5, 6e6))
        return Quote(
            price=round(last_close, 2),
            currency=ccy,
            market_cap=round(last_close * shares_out),
            volume=round(avg_volume * float(rng.lognormal(0, 0.3))),
            avg_volume=round(avg_volume),
            avg_turnover=round(avg_volume * last_close),
            as_of=datetime.now(timezone.utc),
        )

    def _fundamentals(self, rng, q: float) -> Fundamentals:
        gm = 0.25 + q * 0.50 + rng.normal(0, 0.04)
        om = gm * (0.25 + q * 0.35) + rng.normal(0, 0.02)
        nm = om * (0.6 + 0.2 * q)
        rev_g = (q - 0.35) * 0.5 + rng.normal(0, 0.05)
        eps_g = rev_g * (1.1 + 0.4 * q) + rng.normal(0, 0.06)
        # valuation richer for higher quality
        pe = max(5.0, rng.normal(12 + q * 30, 6))
        return Fundamentals(
            revenue_growth=round(float(rev_g), 4),
            eps_growth=round(float(eps_g), 4),
            gross_margin=round(float(np.clip(gm, 0.05, 0.92)), 4),
            operating_margin=round(float(np.clip(om, -0.05, 0.55)), 4),
            net_margin=round(float(np.clip(nm, -0.10, 0.45)), 4),
            fcf=round(float(rng.uniform(-5e8, 8e9) * (0.4 + q))),
            fcf_margin=round(float(np.clip(nm * rng.uniform(0.6, 1.2), -0.1, 0.4)), 4),
            roic=round(float(np.clip(0.04 + q * 0.22 + rng.normal(0, 0.03), -0.05, 0.45)), 4),
            roe=round(float(np.clip(0.05 + q * 0.25 + rng.normal(0, 0.04), -0.1, 0.5)), 4),
            cash=round(float(rng.uniform(2e8, 2e10))),
            debt=round(float(rng.uniform(0, 1.5e10) * (1.3 - q))),
            net_debt_ebitda=round(float(np.clip(rng.normal(2.2 - q * 2.2, 1.0), -2.0, 7.0)), 2),
            pe=round(float(pe), 1),
            forward_pe=round(float(pe * rng.uniform(0.8, 1.0)), 1),
            ev_ebitda=round(float(max(3.0, rng.normal(8 + q * 16, 4))), 1),
            ev_sales=round(float(max(0.3, rng.normal(1 + q * 8, 2))), 2),
            ps=round(float(max(0.2, rng.normal(1 + q * 7, 2))), 2),
            pb=round(float(max(0.3, rng.normal(1.5 + q * 6, 2))), 2),
            fcf_yield=round(float(np.clip(rng.normal(0.06 - q * 0.02, 0.03), -0.05, 0.15)), 4),
            dividend_yield=round(float(np.clip(rng.normal(0.025 * (1 - q), 0.015), 0.0, 0.08)), 4),
            as_of=pd.Timestamp.today().date(),
        )

    def _catalysts(self, rng, q: float) -> Catalysts:
        dte = int(rng.integers(2, 75))
        return Catalysts(
            next_earnings_date=(pd.Timestamp.today() + pd.Timedelta(days=dte)).date(),
            days_to_earnings=dte,
            recent_guidance=rng.choice(["raised", "maintained", "cut", None]),
            analyst_revision_trend=round(float(np.clip(rng.normal((q - 0.4) * 1.2, 0.3), -1, 1)), 2),
            insider_net_buying=round(float(rng.normal((q - 0.5) * 2e6, 1e6))),
            buyback_active=bool(rng.random() < (0.3 + q * 0.4)),
            dilution_risk=bool(rng.random() < (0.35 * (1 - q))),
            short_interest_pct=round(float(np.clip(rng.normal(0.04 + (1 - q) * 0.08, 0.03), 0, 0.4)), 4),
        )

    def _news(self, rng, ticker: str, q: float) -> list[NewsItem]:
        n = int(rng.integers(3, 7))
        items: list[NewsItem] = []
        now = datetime.now(timezone.utc)
        for i in range(n):
            tmpl = _HEADLINES[rng.integers(0, len(_HEADLINES))]
            direction = "raises" if rng.random() < (0.3 + q * 0.4) else "cuts"
            title = tmpl.format(name=ticker, dir=direction)
            hours = int(rng.integers(2, 240))
            items.append(NewsItem(
                title=title,
                url=f"https://news.mock.local/{ticker.lower()}/{i}",
                source="MockWire",
                timestamp=now - pd.Timedelta(hours=hours).to_pytimedelta(),
                summary="Synthetic headline for offline/demo mode.",
                sentiment=round(float(np.clip(rng.normal((q - 0.5), 0.4), -1, 1)), 2),
            ))
        items.sort(key=lambda x: x.timestamp, reverse=True)
        return items


_MOCK = MockProvider()


def mock_provider() -> MockProvider:
    return _MOCK
