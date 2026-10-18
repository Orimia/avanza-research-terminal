"""Plain-language layer tests: briefs, why-bullets, action sentences,
signal translations, and the weekly letter (all offline)."""
from src.models.schemas import (
    Action,
    AnalystView,
    Holding,
    HoldingAnalysis,
    Recommendation,
    ScoreBreakdown,
    TechnicalSnapshot,
)
from src.reports.plain import (
    action_sentence,
    first_sentence,
    translate_signal,
    why_bullets,
)


def test_first_sentence_trims_and_terminates():
    long = ("Novo Nordisk A/S engages in research, development, manufacture and "
            "marketing of pharmaceutical products worldwide. It operates in two "
            "segments.")
    s = first_sentence(long)
    assert s.endswith(".") and "segments" not in s
    assert first_sentence(None) is None
    assert first_sentence("   ") is None
    assert len(first_sentence("word " * 100, max_len=80)) <= 80


def test_why_bullets_are_evidence_based():
    rec = Recommendation(
        ticker="NVO", exchange="US", action=Action.BUY, confidence="High",
        one_liner="", main_reason="", biggest_risk="", price=100.0, currency="USD",
        score=ScoreBreakdown(composite=75, quality=92, growth=84, valuation=40),
        analyst=AnalystView(target_mean=125.0, n_analysts=24),
        technicals=TechnicalSnapshot(ret_3m=0.13, price_vs_ma200=0.06),
        dividend_yield=0.025)
    ws = why_bullets(rec)
    joined = " ".join(ws)
    assert 2 <= len(ws) <= 4
    assert "quality" in joined.lower() and "24 analysts" in joined
    assert "+25%" in joined and "Up 13%" in joined
    # empty rec -> no invented reasons
    bare = Recommendation(ticker="X", exchange="US", action=Action.BUY,
                          confidence="Low", one_liner="", main_reason="",
                          biggest_risk="", score=ScoreBreakdown(composite=50))
    assert why_bullets(bare) == []


def test_action_sentence_is_concrete():
    ha = HoldingAnalysis(
        holding=Holding(ticker="ACME", exchange="US", shares=5, average_cost=80.0),
        name="Acme Corp", action=Action.SELL, unrealized_pct=-0.15,
        score=ScoreBreakdown(composite=42), trade_shares=-5, trade_sek=-2500.0)
    s = action_sentence(ha, "Acme operates a global payments platform.")
    assert s.startswith("Sell all 5 Acme Corp shares")
    assert "2,500 kr" in s and "payments platform" in s
    assert "-15% on it since buying" in s
    buy = HoldingAnalysis(
        holding=Holding(ticker="VOLV-B", exchange="ST", shares=10, average_cost=250.0),
        name="Volvo B", action=Action.BUY,
        score=ScoreBreakdown(composite=69), trade_shares=1, trade_sek=300.0)
    assert action_sentence(buy).startswith("Buy 1 more share of Volvo B")


def test_translate_signal_plain_language():
    t = translate_signal("RSI_EXTREME", "WATCH", "RKLB.US", "RSI 28 oversold — RKLB",
                        state="oversold")
    assert "RKLB" in t and "RSI" not in t          # jargon removed
    assert "washed out" in t
    assert "overheated" in translate_signal("RSI_EXTREME", "TRIM", "SEB-A.ST",
                                            "RSI 81 overbought — SEB-A",
                                            state="overbought")
    nb = translate_signal("NEW_BUY", "BUY", "TSM.US", "New BUY — TSM (score 81)", value=81)
    assert "TSM" in nb and "81" in nb
    assert "multi-month high" in translate_signal("BREAKOUT", "WATCH", "KLAC.US", "t")
    assert "long-term trend" in translate_signal("MA_CROSS", "REVIEW", "HM-B.ST", "t",
                                                 state="below200")


def test_weekly_letter_builds_offline():
    from src.engine.notify import build_weekly_letter
    # offline: holdings resolve to mock -> letter still builds without crashing
    text = build_weekly_letter()
    assert isinstance(text, str) and len(text) > 0
