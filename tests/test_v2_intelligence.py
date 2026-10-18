"""V2 adaptive-intelligence tests: regime, X-ray/Monte Carlo, discipline,
tickets, paper ledger, and signal efficacy. All offline (synthetic data)."""
import math
from datetime import date, datetime, timedelta, timezone

from src.config import get_config
from src.models.schemas import (
    Action,
    Holding,
    HoldingAnalysis,
    PositionSizing,
    PriceBar,
    Quote,
    Recommendation,
    RiskReward,
    ScoreBreakdown,
    SourceCoverage,
    StockData,
    TechnicalSnapshot,
)
from src.scoring.regime import RISK_OFF, RISK_ON, UNKNOWN, apply_regime, classify


# --- helpers --------------------------------------------------------------- #
def _mk(closes, ticker="X", exchange="US", mock=False) -> StockData:
    bars = [PriceBar(date=date(2024, 1, 1) + timedelta(days=i), open=c, high=c, low=c, close=c)
            for i, c in enumerate(closes)]
    return StockData(ticker=ticker, exchange=exchange, currency="USD", price_history=bars,
                     quote=Quote(price=closes[-1], currency="USD"),
                     coverage=SourceCoverage(is_mock=mock), is_mock=mock,
                     fetched_at=datetime.now(timezone.utc))


_UP = [100 * (1.003 ** i) for i in range(300)]
_DOWN = [300 * (0.997 ** i) for i in range(300)]


# --- index symbols + regime ------------------------------------------------ #
def test_index_symbols_pass_through():
    from src.data.yahoo_client import yahoo_symbol
    assert yahoo_symbol("^GSPC", "US") == "^GSPC"
    assert yahoo_symbol("^OMX", "ST") == "^OMX"


def test_regime_classification_and_thresholds():
    assert classify([_mk(_UP, "^A")]).label == RISK_ON
    assert classify([_mk(_DOWN, "^A")]).label == RISK_OFF
    assert classify([_mk(_UP, "^A", mock=True)]).label == UNKNOWN

    cfg = get_config()
    base = float(cfg.get("decisions.buy_min_composite", 68))
    off_cfg, note = apply_regime(cfg, classify([_mk(_DOWN, "^A")]))
    assert float(off_cfg.get("decisions.buy_min_composite")) == base + 6
    assert "risk-off" in note
    on_cfg, _ = apply_regime(cfg, classify([_mk(_UP, "^A")]))
    assert float(on_cfg.get("decisions.buy_min_composite")) == base - 2
    # unknown regime leaves the config untouched
    same_cfg, _ = apply_regime(cfg, classify([_mk(_UP, "^A", mock=True)]))
    assert same_cfg is cfg
    assert float(cfg.get("decisions.buy_min_composite")) == base   # never mutated


# --- portfolio X-ray + Monte Carlo ---------------------------------------- #
def _corr_universe():
    rets = [0.01 * math.sin(i / 3.0) for i in range(280)]
    a, b, c = [100.0], [100.0], [100.0]
    for r in rets:
        a.append(a[-1] * (1 + r))
        b.append(b[-1] * (1 + r))
        c.append(c[-1] * (1 - r))
    return {"AAA": _mk(a, "AAA"), "BBB": _mk(b, "BBB"), "CCC": _mk(c, "CCC")}


def test_xray_clusters_and_effective_bets():
    from src.portfolio.intelligence import build_xray
    datas = _corr_universe()
    holdings = [Holding(ticker=t, exchange="US", shares=1, average_cost=1) for t in datas]
    x = build_xray(holdings, {t: 100.0 for t in datas}, datas)
    assert x.clusters == [["AAA", "BBB"]]          # the identical pair is ONE bet
    assert x.effective_bets is not None and x.effective_bets > 1.5
    assert x.avg_corr is not None


def test_monte_carlo_deterministic_and_ordered():
    from src.portfolio.intelligence import build_xray, monte_carlo
    datas = _corr_universe()
    holdings = [Holding(ticker=t, exchange="US", shares=1, average_cost=1) for t in datas]
    x = build_xray(holdings, {t: 100.0 for t in datas}, datas)
    mc1, mc2 = monte_carlo(x, datas), monte_carlo(x, datas)
    assert mc1 is not None and mc1.p5 <= mc1.p50 <= mc1.p95
    assert mc1.p50 == mc2.p50                       # seeded → reproducible
    assert 0.0 <= mc1.prob_loss <= 1.0 and mc1.mdd_p50 <= 0.0


# --- discipline engine ------------------------------------------------------ #
def _ha(action, *, upct=None, quality=50.0, ticker="T", shares=2.0):
    return HoldingAnalysis(
        holding=Holding(ticker=ticker, exchange="US", shares=shares, average_cost=10),
        action=action, unrealized_pct=upct,
        score=ScoreBreakdown(composite=55, quality=quality),
    )


class _FakeReview:
    def __init__(self, holdings):
        self.holdings = holdings


def test_discipline_flags():
    from src.portfolio.discipline import check_holdings, check_new_buys
    rules = {f.rule for f in check_holdings(_FakeReview([
        _ha(Action.BUY, upct=-0.25, ticker="AVG"),                    # averaging down
        _ha(Action.SELL, upct=-0.30, quality=80.0, ticker="QLT"),     # quality dump
        *[_ha(Action.TRIM, ticker=f"C{i}") for i in range(6)],        # churn (8 > 6)
    ]))}
    assert {"averaging-down", "quality-dump", "churn"} <= rules

    fomo_rec = Recommendation(
        ticker="HOT", exchange="US", action=Action.BUY, confidence="High",
        one_liner="", main_reason="", biggest_risk="",
        score=ScoreBreakdown(composite=75),
        technicals=TechnicalSnapshot(rsi14=82, price_vs_ma50=0.2))
    assert [f.rule for f in check_new_buys([fomo_rec])] == ["fomo-entry"]
    assert check_holdings(_FakeReview([_ha(Action.HOLD)])) == []


# --- order tickets ----------------------------------------------------------- #
def test_tickets_from_recommendation_and_holding():
    from src.portfolio.tickets import format_ticket, from_holding, from_recommendation
    rec = Recommendation(
        ticker="NVDA", exchange="US", action=Action.BUY, confidence="High",
        one_liner="", main_reason="", biggest_risk="",
        score=ScoreBreakdown(composite=80), price=100.0, currency="USD",
        risk_reward=RiskReward(entry=100, stop_loss=88, take_profit=125,
                               upside_pct=0.25, downside_pct=0.12, rr_ratio=2.1),
        sizing=PositionSizing(currency="USD", price_local=100, fx_to_sek=10,
                              price_sek=1000, target_weight_pct=5, target_sek=3000,
                              shares=3, actual_sek=3000, actual_weight_pct=5))
    t = from_recommendation(rec)
    assert t.side == "BUY" and t.qty == 3 and t.limit_price == 100.2   # pay up 0.2%
    assert t.stop == 88 and "never places orders" in format_ticket(t)

    ha = _ha(Action.SELL, ticker="ACME")
    ha.current_price, ha.trade_shares, ha.trade_sek = 50.0, -2, -1000.0
    ts = from_holding(ha)
    assert ts.side == "SELL" and ts.qty == 2 and ts.limit_price == 49.9  # sell down 0.2%
    fund = _ha(Action.TRIM, ticker="FUND")
    fund.trade_shares, fund.trade_sek, fund.current_price = 0, -2500.0, None
    tf = from_holding(fund)
    assert tf.limit_price is None and "SEK-amount" in tf.note


# --- paper ledger ------------------------------------------------------------ #
class _Sig:
    def __init__(self, stype, symbol, action, title="t"):
        self.type = type("T", (), {"value": stype})()
        self.symbol, self.action, self.title = symbol, action, title


def test_paper_ledger_open_close(monkeypatch):
    import src.data.provider as provider
    from src.portfolio.paper import process_signals, track_record
    live = _mk([100.0] * 130, "PPR")
    monkeypatch.setattr(provider, "get_stock_data",
                        lambda *a, **k: live)
    fx = {"USDSEK": 10.0, "SEKSEK": 1.0}
    n = process_signals([_Sig("NEW_BUY", "PPR.US", "BUY")], fx)
    assert n == 1
    n2 = process_signals([_Sig("NEW_BUY", "PPR.US", "BUY")], fx)   # no duplicate open
    assert n2 == 0
    live.quote.price = 110.0
    assert process_signals([_Sig("HOLDING_ACTION", "PPR.US", "SELL")], fx) == 1
    tr = track_record(fx)
    closed = [r for r in tr.closed_rows if r["symbol"] == "PPR.US"]
    assert closed and closed[0]["pnl_sek"] > 0 and tr.hit_rate is not None


# --- signal efficacy ---------------------------------------------------------- #
def test_signal_efficacy_scores_old_signals():
    from src.backtest.efficacy import signal_efficacy
    from src.storage.db import get_db
    db = get_db()
    rising = _mk([100 + i for i in range(90)], "EFF")     # ends 45 days ago → fwd > 0
    db.cache_put(rising)
    old = (rising.price_history[10].date).isoformat() + "T10:00:00+00:00"
    for i in range(3):
        db.conn.execute(
            "INSERT INTO alerts_log(symbol, type, action, severity, title, detail, "
            "value, created_at, sent, channels) VALUES(?,?,?,?,?,?,?,?,0,'')",
            ("EFF.US", "NEW_BUY", "BUY", "warn", f"sig{i}", "", 70.0, old))
    db.conn.commit()
    rep = signal_efficacy()
    row = next((r for r in rep.rows if r.signal_type == "NEW_BUY"), None)
    assert row is not None and row.n >= 3
    assert row.median_fwd_pct > 0 and row.hit_rate == 1.0
