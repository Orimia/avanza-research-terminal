"""Schema construction + missing-data semantics."""
from datetime import date

from src.models.schemas import (
    Action,
    Fundamentals,
    PriceBar,
    Recommendation,
    ScoreBreakdown,
    SourceCoverage,
)


def test_fundamentals_optional_fields_default_none():
    f = Fundamentals()
    assert f.pe is None and f.revenue_growth is None
    assert f.available_fields() == 0
    f2 = Fundamentals(pe=12.0, revenue_growth=0.1)
    assert f2.available_fields() == 2


def test_source_coverage_quality():
    assert SourceCoverage(is_mock=True).quality == "Mock"
    full = SourceCoverage(is_mock=False, price=True, fundamentals=True, news=True, catalysts=True)
    assert full.quality == "Good"
    weak = SourceCoverage(is_mock=False, price=True)
    assert weak.quality == "Weak"


def test_recommendation_round_trip():
    rec = Recommendation(
        ticker="VOLV-B", exchange="ST", action=Action.BUY,
        confidence="High", one_liner="x", main_reason="y", biggest_risk="z",
        score=ScoreBreakdown(composite=72.0),
    )
    dumped = rec.model_dump()
    restored = Recommendation.model_validate(dumped)
    assert restored.action == Action.BUY
    assert restored.symbol == "VOLV-B.ST"


def test_price_bar():
    b = PriceBar(date=date(2025, 1, 2), open=1, high=2, low=0.5, close=1.5)
    assert b.close == 1.5 and b.volume == 0.0
