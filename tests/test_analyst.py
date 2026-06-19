"""Analyst-target parsing (Yahoo) + propagation into recommendations."""
from src.data.provider import get_stock_data
from src.data.yahoo_client import YahooClient, yahoo_symbol
from src.models.schemas import AnalystView
from src.scoring.composite import build_recommendation


def test_yahoo_symbol_mapping():
    assert yahoo_symbol("TSLA", "US") == "TSLA"
    assert yahoo_symbol("VOLV-B", "ST") == "VOLV-B.ST"
    assert yahoo_symbol("NOVO-B", "CO") == "NOVO-B.CO"   # Copenhagen
    assert yahoo_symbol("EQNR", "OL") == "EQNR.OL"       # Oslo
    assert yahoo_symbol("DBK", "EU") == "DBK.DE"
    assert yahoo_symbol("STM", "EU") == "STMPA.PA"
    assert yahoo_symbol("ZZZ", "EU") is None             # unknown EU ticker


def test_analyst_view_parsing_and_upside():
    c = YahooClient()
    info = {"targetMeanPrice": 380.0, "targetHighPrice": 420.0, "targetLowPrice": 300.0,
            "numberOfAnalystOpinions": 18, "recommendationKey": "buy",
            "recommendationMean": 2.1}
    a = c._analyst(info)
    assert a.target_mean == 380.0 and a.recommendation == "buy" and a.n_analysts == 18
    assert abs(a.upside(340.0) - (380.0 / 340.0 - 1)) < 1e-9
    assert a.upside(None) is None
    assert c._analyst({}) is None


def test_yahoo_fundamentals_units_and_ndte():
    c = YahooClient()
    info = {"grossMargins": 0.45, "profitMargins": 0.20, "trailingPE": 22.0,
            "returnOnEquity": 0.18, "totalDebt": 1000.0, "totalCash": 200.0,
            "ebitda": 400.0}
    f = c._fundamentals(info)
    assert f.gross_margin == 0.45 and f.pe == 22.0 and f.roe == 0.18
    assert abs(f.net_debt_ebitda - ((1000 - 200) / 400)) < 1e-9


def test_recommendation_carries_analyst_target():
    d = get_stock_data("VOLV-B", "ST")  # mock offline
    d.analyst = AnalystView(target_mean=d.quote.price * 1.2, recommendation="buy", n_analysts=10)
    rec = build_recommendation(d, {"SEKSEK": 1.0})
    assert rec.price == d.quote.price
    assert rec.analyst_target == d.quote.price * 1.2
    assert abs(rec.analyst_upside - 0.2) < 1e-6
