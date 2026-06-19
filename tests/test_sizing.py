"""Position sizing: whole shares, SEK conversion, risk caps, warnings."""
from src.models.schemas import Action, ScoreBreakdown
from src.portfolio.sizing import size_position, suggest_weight

FX = {"SEKSEK": 1.0, "USDSEK": 10.5, "EURSEK": 11.3}


def test_whole_shares_sek():
    s = size_position(100.0, "SEK", FX, 100_000, 0.05)
    assert s.shares == 50            # floor(5000 / 100)
    assert s.actual_sek == 5000
    assert s.currency_risk is None   # base currency


def test_whole_shares_never_fractional_and_within_budget():
    s = size_position(333.0, "SEK", FX, 100_000, 0.05)
    assert isinstance(s.shares, int)
    assert s.actual_sek <= 100_000 * 0.05 + 1e-6


def test_usd_conversion_and_currency_risk():
    s = size_position(100.0, "USD", FX, 100_000, 0.05)
    assert s.price_sek == 1050.0
    assert s.shares == 4             # floor(5000 / 1050)
    assert s.currency_risk is not None


def test_high_risk_cap_applied():
    s = size_position(100.0, "SEK", FX, 100_000, 0.05, high_risk=True)
    # high-risk cap (2%) should override the requested 5%
    assert s.target_weight_pct <= 2.01


def test_liquidity_warning_triggers():
    # tiny average turnover -> order is a big fraction of ADV
    s = size_position(100.0, "SEK", FX, 1_000_000, 0.05, avg_turnover_local=200_000)
    assert s.liquidity_warning is not None


def test_suggest_weight_avoid_is_zero():
    b = ScoreBreakdown(composite=75)
    assert suggest_weight(Action.AVOID, b, high_risk=False) == 0.0
    assert suggest_weight(Action.BUY, b, high_risk=False) > 0
