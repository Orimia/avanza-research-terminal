"""Scoring engine: helpers, sub-scores, composite, decision."""
from src.data.provider import get_stock_data
from src.models.schemas import Action
from src.scoring import clamp, lin, wavg
from src.scoring.composite import analyze, confidence, decide_new


def test_helpers():
    assert clamp(150) == 100 and clamp(-5) == 0
    assert lin(0.5, 0, 1, 0, 100) == 50
    assert lin(None, 0, 1) is None
    # inverse mapping (cheaper == higher)
    assert lin(8, 60, 8, 10, 95) == 95
    assert wavg([(80, 1), (None, 1), (40, 1)]) == 60


def test_composite_in_range_and_covered():
    data = get_stock_data("VOLV-B", "ST")
    fx = {"SEKSEK": 1.0}
    a = analyze(data, fx)
    assert 0 <= a.breakdown.composite <= 100
    assert 0 < a.breakdown.coverage <= 1.0
    # mock provides all sub-scores
    for v in (a.breakdown.quality, a.breakdown.growth, a.breakdown.momentum,
              a.breakdown.valuation, a.breakdown.catalyst, a.breakdown.risk):
        assert v is None or 0 <= v <= 100


def test_decision_and_confidence_types():
    data = get_stock_data("AAPL", "US")
    fx = {"SEKSEK": 1.0, "USDSEK": 10.5}
    a = analyze(data, fx)
    action, reason, risk = decide_new(data, a.breakdown, a.risk_reward)
    assert isinstance(action, Action)
    assert reason and risk
    # mock data must never produce HIGH confidence
    assert confidence(data, a.breakdown, a.risk_reward).value in {"Medium", "Low"}


def test_risk_reward_positive_rr():
    data = get_stock_data("ERIC-B", "ST")
    a = analyze(data, {"SEKSEK": 1.0})
    if a.risk_reward:
        assert a.risk_reward.stop_loss < a.risk_reward.entry < a.risk_reward.take_profit
        assert a.risk_reward.rr_ratio > 0
