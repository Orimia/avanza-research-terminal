"""Real-client parsing tests (no network) — units & field mapping correctness.

We monkeypatch each client's ``_get`` with canned API responses so we can verify
parsing/units without API keys, locking in the Finnhub percent->fraction fix and
the removal of mislabeled fields.
"""
from datetime import date, timedelta

from src.data.borsdata_client import BorsdataClient
from src.data.eodhd_client import EodhdClient
from src.data.finnhub_client import FinnhubClient


def test_finnhub_units_and_dropped_fields(monkeypatch):
    client = FinnhubClient()
    monkeypatch.setattr(client, "available", lambda: True)

    def fake_get(path, params=None):
        if path == "/quote":
            return {"c": 100.0}
        if path == "/stock/profile2":
            return {"name": "Test Co", "finnhubIndustry": "Technology",
                    "country": "US", "currency": "USD", "marketCapitalization": 1000}
        if path == "/stock/metric":
            return {"metric": {
                "grossMarginTTM": 45.2, "operatingMarginTTM": 20.1,
                "netProfitMarginTTM": 14.0, "roeTTM": 18.5, "roiTTM": 15.0,
                "revenueGrowthTTMYoy": 12.3, "epsGrowthTTMYoy": 20.0,
                "peTTM": 22.0, "psTTM": 5.0, "pbQuarterly": 4.0,
                "dividendYieldIndicatedAnnual": 0.8,
                "10DayAverageTradingVolume": 50.3,
                "netDebtToTotalCapital": 0.3,
                "currentEv/freeCashFlowTTM": 25.0,
            }}
        if path == "/calendar/earnings":
            return {"earningsCalendar": [{"date": (date.today() + timedelta(days=30)).isoformat()}]}
        if path == "/company-news":
            return [{"headline": "h", "url": "http://x", "source": "S",
                     "datetime": 1700000000, "summary": "s"}]
        return None

    monkeypatch.setattr(client, "_get", fake_get)
    data = client.fetch("TEST", "US")
    assert data is not None and not data.is_mock
    f = data.fundamentals
    # percentages converted to fractions
    assert abs(f.gross_margin - 0.452) < 1e-9
    assert abs(f.revenue_growth - 0.123) < 1e-9
    assert abs(f.roe - 0.185) < 1e-9
    assert abs(f.dividend_yield - 0.008) < 1e-9
    # ratios left as-is
    assert f.pe == 22.0
    # mislabeled fields dropped (not substituted with a different ratio)
    assert f.net_debt_ebitda is None
    assert f.ev_ebitda is None
    # 10d avg volume scaled from millions, turnover derived
    assert data.quote.avg_volume == 50.3e6
    assert data.quote.avg_turnover == 50.3e6 * 100.0
    # marketCapitalization (1000 millions) -> 1e9
    assert data.quote.market_cap == 1e9


def test_eodhd_parsing_decimals(monkeypatch):
    client = EodhdClient()
    monkeypatch.setattr(client, "available", lambda: True)

    bars = [{"date": f"2025-01-0{i}", "open": 10 + i, "high": 11 + i,
             "low": 9 + i, "close": 10 + i, "adjusted_close": 10 + i,
             "volume": 1_000_000} for i in range(1, 8)]

    def fake_get(path, params=None):
        if path.startswith("/eod/"):
            return bars
        if path.startswith("/fundamentals/"):
            return {
                "General": {"Name": "Test", "Sector": "Technology", "CurrencyCode": "USD"},
                "Highlights": {"MarketCapitalization": 1e9, "PERatio": 22,
                               "ProfitMargin": 0.14, "OperatingMarginTTM": 0.20,
                               "ReturnOnEquityTTM": 0.18, "QuarterlyRevenueGrowthYOY": 0.12,
                               "QuarterlyEarningsGrowthYOY": 0.20, "DividendYield": 0.01},
                "Valuation": {"ForwardPE": 19, "EnterpriseValueEbitda": 15,
                              "EnterpriseValueRevenue": 6, "PriceSalesTTM": 5,
                              "PriceBookMRQ": 4},
            }
        if path.startswith("/news"):
            return [{"title": "t", "link": "http://x", "date": "2025-01-05T00:00:00+00:00"}]
        return None

    monkeypatch.setattr(client, "_get", fake_get)
    data = client.fetch("TEST", "US")
    assert data is not None and not data.is_mock
    assert len(data.price_history) == 7
    f = data.fundamentals
    assert f.net_margin == 0.14 and f.operating_margin == 0.20
    assert f.pe == 22 and f.forward_pe == 19 and f.ev_ebitda == 15
    assert data.coverage.fundamentals and data.coverage.price


def test_borsdata_parsing_and_instruments_memoized(monkeypatch):
    client = BorsdataClient()
    monkeypatch.setattr(client, "available", lambda: True)
    calls = {"instruments": 0}

    def fake_get(path, params=None):
        if path == "/instruments":
            calls["instruments"] += 1
            return {"instruments": [{"insId": 1, "ticker": "VOLV B", "name": "Volvo"}]}
        if path == "/instruments/1/stockprices":
            return {"stockPricesList": [
                {"d": f"2025-01-0{i}", "o": 100 + i, "h": 102 + i,
                 "l": 99 + i, "c": 101 + i, "v": 1_000_000} for i in range(1, 8)]}
        if path == "/instruments/1/reports/year":
            return {"reports": [
                {"revenues": 1100, "earnings_Per_Share": 11.0, "gross_Income": 440,
                 "operating_Income": 220, "profit_To_Equity_Holders": 150, "free_Cash_Flow": 90},
                {"revenues": 1000, "earnings_Per_Share": 10.0, "gross_Income": 400,
                 "operating_Income": 200, "profit_To_Equity_Holders": 140, "free_Cash_Flow": 80},
            ]}
        return None

    monkeypatch.setattr(client, "_get", fake_get)
    # ticker "VOLV B" -> normalised "VOLV-B"
    d1 = client.fetch("VOLV-B", "ST")
    d2 = client.fetch("VOLV-B", "ST")
    assert d1 is not None and d2 is not None
    assert d1.currency == "SEK" and len(d1.price_history) == 7
    f = d1.fundamentals
    assert abs(f.revenue_growth - 0.10) < 1e-9       # (1100-1000)/1000
    assert abs(f.gross_margin - 0.40) < 1e-9         # 440/1100
    assert f.pe is not None and f.pe > 0             # price / EPS
    # instruments list fetched once despite two fetch() calls (memoised)
    assert calls["instruments"] == 1
