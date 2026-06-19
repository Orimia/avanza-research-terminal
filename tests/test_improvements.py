"""Tests for the QA-pass fixes & improvements: dividend units, 52w range,
single-name ceiling, screener presets/badges, pulse dedup."""
from datetime import datetime, timedelta, timezone

from src.config import get_config
from src.data.yahoo_client import YahooClient
from src.dashboard import ui
from src.models.schemas import (
    Action,
    Recommendation,
    ScoreBreakdown,
    TechnicalSnapshot,
)
from src.portfolio.opportunity_cost import decide_holding
from src.scoring.technicals import compute_technicals


# --- dividend yield units (the 100x bug) --------------------------------- #
def test_dividend_yield_percent_is_normalised():
    c = YahooClient()
    # Yahoo gives dividendYield as a PERCENT: 0.24 means 0.24%, not 24%
    f = c._fundamentals({"dividendYield": 0.24})
    assert abs(f.dividend_yield - 0.0024) < 1e-9
    f2 = c._fundamentals({"dividendYield": 3.95})            # CVX ~3.95%
    assert abs(f2.dividend_yield - 0.0395) < 1e-9
    # trailingAnnualDividendYield (a fraction) is preferred when present
    f3 = c._fundamentals({"trailingAnnualDividendYield": 0.0587, "dividendYield": 5.87})
    assert abs(f3.dividend_yield - 0.0587) < 1e-9


# --- 52-week range ------------------------------------------------------- #
def test_52w_range_computed():
    from datetime import date as _d
    from src.models.schemas import PriceBar, Quote, SourceCoverage, StockData
    closes = [100 + i for i in range(260)]   # rising 100..359, current=359 = high
    bars = [PriceBar(date=_d(2024, 1, 1) + timedelta(days=i), open=c, high=c, low=c, close=c)
            for i, c in enumerate(closes)]
    d = StockData(ticker="X", exchange="US", currency="USD", price_history=bars,
                  quote=Quote(price=closes[-1], currency="USD"),
                  coverage=SourceCoverage(is_mock=False), fetched_at=datetime.now(timezone.utc))
    t = compute_technicals(d)
    assert t.wk52_high == max(closes[-252:]) and t.wk52_low == min(closes[-252:])
    assert t.pct_in_range is not None and t.pct_in_range > 0.99   # at the high


# --- single-name ceiling (the GOOG contradiction) ------------------------ #
def test_single_name_ceiling_not_buy_size():
    cfg = get_config()  # max_single_position_pct = 0.25
    b = ScoreBreakdown(composite=70, momentum=67, quality=91)
    # 21.7% is over the old 8% but UNDER the 25% ceiling -> HOLD, not TRIM
    action, _ = decide_holding(None, b, weight_pct=21.7, unrealized_pct=0.1, cfg=cfg,
                               kind="stock", analyst_upside=0.17)
    assert action == Action.HOLD
    # 30% exceeds the ceiling -> TRIM
    action2, _ = decide_holding(None, b, weight_pct=30.0, unrealized_pct=0.1, cfg=cfg,
                                kind="stock", analyst_upside=0.17)
    assert action2 == Action.TRIM


# --- screener presets + badges ------------------------------------------- #
def _rec(**kw):
    base = dict(ticker="X", exchange="US", action=Action.BUY, confidence="High",
                one_liner="", main_reason="", biggest_risk="",
                score=ScoreBreakdown(composite=70, quality=60, growth=60, valuation=60, momentum=60))
    base.update(kw)
    return Recommendation(**base)


def test_preset_rank_changes_order():
    val = _rec(score=ScoreBreakdown(composite=65, quality=40, growth=40, valuation=95, momentum=40))
    mom = _rec(score=ScoreBreakdown(composite=65, quality=40, growth=40, valuation=40, momentum=95))
    assert ui.preset_rank(val, "value") > ui.preset_rank(mom, "value")
    assert ui.preset_rank(mom, "momentum") > ui.preset_rank(val, "momentum")


def test_income_preset_filters_non_payers():
    payer = _rec(dividend_yield=0.03)
    nonpayer = _rec(dividend_yield=0.0)
    assert ui.preset_keep(payer, "income") and not ui.preset_keep(nonpayer, "income")


def test_pick_badges():
    r = _rec(dividend_yield=0.04, days_to_earnings=5,
             technicals=TechnicalSnapshot(volatility=0.6))
    badges = ui.pick_badges(r)
    assert "div" in badges and "Earnings" in badges and "High vol" in badges
    # affordability badge when a whole share exceeds the target size
    from src.models.schemas import PositionSizing
    r2 = _rec(sizing=PositionSizing(currency="USD", price_local=1, fx_to_sek=10, price_sek=10,
                                    target_weight_pct=5, target_sek=1000, shares=0,
                                    actual_sek=0, actual_weight_pct=0))
    assert "your size" in ui.pick_badges(r2)


# --- pulse dedup --------------------------------------------------------- #
def test_pulse_skips_unchanged_all_hold(monkeypatch):
    from src.engine import notify
    from src.engine.scanner import PulseResult
    from src.storage.db import get_db
    db = get_db()
    db.conn.execute("DELETE FROM signal_state WHERE dedup_key='__pulse__'")
    db.conn.commit()
    sent = {"n": 0}
    monkeypatch.setattr(notify, "_send", lambda *a, **k: sent.__setitem__("n", sent["n"] + 1) or True)
    res = PulseResult(value_sek=10000, actions=[], n_holdings=5)
    assert notify.dispatch_pulse(res) is True      # first of day -> sends
    assert notify.dispatch_pulse(res) is False     # unchanged all-HOLD -> skipped
    assert sent["n"] == 1
