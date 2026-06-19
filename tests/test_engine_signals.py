"""Signal detectors + emit/de-dup decision logic (pure, offline)."""
from datetime import date, datetime, timedelta, timezone

from src.engine import signals as S
from src.engine.scanner import _decide_emit
from src.models.schemas import (
    Action,
    Catalysts,
    Holding,
    PriceBar,
    Quote,
    ScoreBreakdown,
    SourceCoverage,
    StockData,
    TechnicalSnapshot,
)

TODAY = date.today().isoformat()


def _stock(closes, ticker="TST", exchange="US", catalysts=None):
    bars = [PriceBar(date=date(2024, 1, 1) + timedelta(days=i), open=c, high=c,
                     low=c, close=c, volume=1000) for i, c in enumerate(closes)]
    return StockData(ticker=ticker, exchange=exchange, currency="USD",
                     quote=Quote(price=closes[-1], currency="USD", avg_turnover=1e8),
                     price_history=bars, catalysts=catalysts,
                     coverage=SourceCoverage(provider="test", price=True, is_mock=False),
                     is_mock=False, fetched_at=datetime.now(timezone.utc))


def test_big_move():
    assert S.big_move(_stock([100, 100, 110]), 0.06, TODAY) is not None  # +10%
    assert S.big_move(_stock([100, 100, 101]), 0.06, TODAY) is None       # +1%
    sig = S.big_move(_stock([100, 90]), 0.06, TODAY)                      # -10%
    assert sig.recurring_daily and sig.value < 0


def test_breakout():
    up = S.breakout(_stock(list(range(1, 130))), lookback=120)     # new high
    assert up.alert_worthy is True and up.state_value == "breakout"
    flat = S.breakout(_stock([100] * 130 + [90]), lookback=120)    # below highs
    assert flat.alert_worthy is False


def test_rsi_and_ma():
    d = _stock([100, 101, 102])
    ob = S.rsi_extreme(d, TechnicalSnapshot(rsi14=82), 75, 30)
    assert ob.alert_worthy and ob.state_value == "overbought"
    neutral = S.rsi_extreme(d, TechnicalSnapshot(rsi14=55), 75, 30)
    assert neutral.alert_worthy is False
    below = S.ma_cross(d, TechnicalSnapshot(price_vs_ma200=-0.03))
    assert below.state_value == "below200" and below.action == "REVIEW"


def test_stop_take():
    h = Holding(ticker="TST", exchange="US", shares=10, average_cost=100, currency="USD")
    # price fell from a high of 130 to 100 -> >12% off high -> stop triggered
    sigs = S.stop_take(_stock([130, 125, 100]), h, stop_pct=0.12, tp_pct=0.25)
    stop = [s for s in sigs if s.type == S.SignalType.STOP_HIT][0]
    assert stop.alert_worthy is True
    # price 130 vs cost 100 -> +30% -> take-profit triggered
    sigs2 = S.stop_take(_stock([100, 120, 130]), h, stop_pct=0.12, tp_pct=0.25)
    tp = [s for s in sigs2 if s.type == S.SignalType.TAKEPROFIT_HIT][0]
    assert tp.alert_worthy is True


def test_new_buy_and_holding_action():
    d = _stock([100, 101])
    buy = S.new_buy(d, ScoreBreakdown(composite=75), Action.BUY, 68)
    assert buy.alert_worthy and buy.state_value == "BUY"
    notbuy = S.new_buy(d, ScoreBreakdown(composite=60), Action.AVOID, 68)
    assert notbuy.alert_worthy is False
    sell = S.holding_action(d, Action.SELL, "thesis broken")
    assert sell.alert_worthy and sell.severity == "critical"
    hold = S.holding_action(d, Action.HOLD, "fine")
    assert hold.alert_worthy is False


def test_earnings_soon():
    cat = Catalysts(next_earnings_date=date.today() + timedelta(days=3), days_to_earnings=3)
    sig = S.earnings_soon(_stock([100, 101], catalysts=cat), within_days=5)
    assert sig.alert_worthy is True
    far = Catalysts(next_earnings_date=date.today() + timedelta(days=40), days_to_earnings=40)
    assert S.earnings_soon(_stock([100, 101], catalysts=far), within_days=5).alert_worthy is False


def test_decide_emit_logic():
    now = datetime.now(timezone.utc)
    sig = S.Signal(symbol="X.US", ticker="X", exchange="US", type=S.SignalType.RSI_EXTREME,
                   state_value="overbought", alert_worthy=True, seed_silently=True)
    # first observation of a seed-silent signal -> don't emit
    assert _decide_emit(None, sig, now, 90) is False
    # transition into a new state -> emit
    prior = {"state_value": "neutral", "last_emitted": None}
    assert _decide_emit(prior, sig, now, 90) is True
    # same state -> no re-emit
    prior_same = {"state_value": "overbought", "last_emitted": now.isoformat()}
    assert _decide_emit(prior_same, sig, now, 90) is False
    # recurring-daily re-arms across days
    mv = S.Signal(symbol="X.US", ticker="X", exchange="US", type=S.SignalType.BIG_MOVE,
                  state_value=TODAY, alert_worthy=True, recurring_daily=True)
    yesterday = (now - timedelta(days=1)).isoformat()
    assert _decide_emit({"state_value": "x", "last_emitted": yesterday}, mv, now, 90) is True
    assert _decide_emit({"state_value": "x", "last_emitted": now.isoformat()}, mv, now, 90) is False
