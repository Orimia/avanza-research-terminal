"""Trust-release tests: one-voice coherence, you-vs-index snapshots,
morning self-report, and translation fixes. Offline."""
from src.models.schemas import Action, Holding, HoldingAnalysis, ScoreBreakdown
from src.reports.plain import action_sentence, discipline_by_symbol, translate_signal


class _FakeReview:
    def __init__(self, holdings):
        self.holdings = holdings


def _ha(action, ticker="T", upct=None, quality=50.0, shares=2.0,
        trade_shares=1, trade_sek=500.0):
    return HoldingAnalysis(
        holding=Holding(ticker=ticker, exchange="US", shares=shares, average_cost=10),
        action=action, unrealized_pct=upct,
        score=ScoreBreakdown(composite=60, quality=quality),
        trade_shares=trade_shares, trade_sek=trade_sek)


def test_one_voice_coherence():
    # a BUY on a deep loser must carry the discipline caution IN the sentence
    ha = _ha(Action.BUY, ticker="LAGGARD", upct=-0.18)
    review = _FakeReview([ha])
    cautions = discipline_by_symbol(review)
    assert "LAGGARD" in cautions and "averaging down" in cautions["LAGGARD"]
    s = action_sentence(ha, caution=cautions["LAGGARD"])
    assert s.startswith("Buy 1 more share") and "CAUTION:" in s and "averaging down" in s
    # no caution -> no CAUTION text
    assert "CAUTION" not in action_sentence(_ha(Action.SELL, upct=0.3))


def test_snapshot_roundtrip_and_ordering():
    from src.storage.db import get_db
    db = get_db()
    db.snapshot_upsert("2099-01-02", 100000.0, 6200.0, 2600.0)
    db.snapshot_upsert("2099-01-03", 101200.0, 6210.0, 2590.0)
    db.snapshot_upsert("2099-01-03", 101500.0, 6212.0, 2591.0)   # same-day upsert
    snaps = db.snapshots()
    days = [s["day"] for s in snaps]
    assert days == sorted(days)                                  # chronological
    assert snaps[-1]["value_sek"] == 101500.0                     # upsert replaced


def test_morning_digest_has_self_report():
    from src.engine.notify import _format_digest
    from src.engine.scanner import ScanResult
    _, text = _format_digest(ScanResult(kind="morning"))
    assert "Engine self-report" in text
    _, close_text = _format_digest(ScanResult(kind="close"))
    assert "Engine self-report" not in close_text                # mornings only


def test_holding_action_translation_strips_ticker_prefix():
    t = translate_signal("HOLDING_ACTION", "TRIM", "ACME.US",
                        "ACME: TRIM 2 sh (~1,000 SEK)")
    assert t == "Your holding ACME: TRIM 2 sh (~1,000 SEK)"
