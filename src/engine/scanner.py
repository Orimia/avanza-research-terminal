"""Scan orchestration: gather → detect → de-dup vs state → persist.

Two scan kinds:
  * **intraday** — fast batch prices over universe+watchlist+holdings; price/
    technical signals + holding stop/take-profit. Runs on a short cadence during
    market hours.
  * **full** (morning/close/manual) — adds fundamentals for holdings, watchlist
    and the top price-ranked candidates: NEW_BUY, holding action changes,
    imminent earnings; also builds the digest context (top buys, holdings review).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.config import Config, get_config
from src.data.fx_client import get_fx_rates
from src.data.provider import get_stock_data, screen_data
from src.engine import signals as S
from src.engine.signals import Signal
from src.models.schemas import Action, HoldingAnalysis, Recommendation
from src.scoring.composite import analyze, build_recommendation
from src.scoring.technicals import compute_technicals
from src.storage.db import get_db
from src.universe import load_universe
from src.utils.logging import get_logger

log = get_logger("engine.scanner")


@dataclass
class ScanResult:
    kind: str
    scanned: int = 0
    emitted: list[Signal] = field(default_factory=list)
    top_buys: list[Recommendation] = field(default_factory=list)
    holdings_review: list[HoldingAnalysis] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class PulseResult:
    value_sek: float = 0.0
    unrealized_pct: float | None = None
    actions: list[HoldingAnalysis] = field(default_factory=list)   # non-HOLD holdings
    top_buys: list[dict] = field(default_factory=list)             # recent NEW_BUY alerts
    n_holdings: int = 0
    errors: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _dedup(entries: list[tuple[str, str]]) -> list[tuple[str, str]]:
    seen, out = set(), []
    for e in entries:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out


def _gather(cfg: Config):
    db = get_db()
    scope = cfg.get("engine.scope", ["nordic", "eu", "us"])
    uni: list[tuple[str, str]] = []
    for region in scope:
        uni.extend(load_universe(region))
    holdings = db.portfolio_all() if cfg.get("engine.include_holdings", True) else []
    wl = []
    if cfg.get("engine.include_watchlist", True):
        wl = [(w["ticker"], w["exchange"]) for w in db.watchlist_all()]
    return _dedup(uni), holdings, _dedup(wl)


def _minutes_since(iso: str | None, now: datetime) -> float:
    if not iso:
        return 1e9
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return 1e9
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now - t).total_seconds() / 60.0


def _decide_emit(prior: dict | None, sig: Signal, now: datetime, cooldown_min: float) -> bool:
    if not sig.alert_worthy:
        return False
    if prior is None:
        return not sig.seed_silently
    le = prior.get("last_emitted")
    if sig.recurring_daily:
        return (le is None) or (le[:10] < now.date().isoformat())
    if le and _minutes_since(le, now) < cooldown_min:
        return False
    return prior.get("state_value") != sig.state_value


def _process(sigs: list[Signal], now: datetime, cfg: Config) -> list[Signal]:
    db = get_db()
    cooldown = float(cfg.get("engine.alerts.cooldown_minutes", 90))
    cap = int(cfg.get("engine.alerts.max_per_scan", 25))
    candidates: list[Signal] = []
    for sig in sigs:
        if not sig.dedup_key:
            continue
        prior = db.signal_state_get(sig.dedup_key)
        if _decide_emit(prior, sig, now, cooldown):
            candidates.append(sig)
        else:
            # record current state without advancing the cooldown clock
            db.signal_state_set(sig.dedup_key, sig.state_value, sig.value, touch_emitted=False)

    order = {"critical": 0, "warn": 1, "info": 2}
    candidates.sort(key=lambda s: order.get(s.severity, 3))
    emitted, held = candidates[:cap], candidates[cap:]
    # only signals we actually emit advance last_emitted; capped-out ones re-arm
    for sig in emitted:
        db.signal_state_set(sig.dedup_key, sig.state_value, sig.value, touch_emitted=True)
    for sig in held:
        db.signal_state_set(sig.dedup_key, sig.state_value, sig.value, touch_emitted=False)
    return emitted


# --------------------------------------------------------------------------- #
# scans
# --------------------------------------------------------------------------- #
def run_intraday() -> ScanResult:
    cfg = get_config()
    a = cfg.get("engine.alerts", {}) or {}
    db = get_db()
    rid = db.scan_run_start("intraday")
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    res = ScanResult(kind="intraday")
    try:
        uni, holdings, wl = _gather(cfg)
        entries = _dedup(uni + wl + [(h.ticker, h.exchange) for h in holdings])
        stocks = screen_data(entries)
        res.scanned = len(stocks)
        hold_by_sym = {h.symbol: h for h in holdings}
        stop_pct = float(cfg.get("risk.default_stop_pct", 0.12))
        tp_pct = float(cfg.get("risk.default_take_profit_pct", 0.25))
        sigs: list[Signal] = []
        for s in stocks:
            tech = compute_technicals(s)
            for det in (
                S.big_move(s, float(a.get("big_move_pct", 0.06)), today),
                S.breakout(s, int(a.get("breakout_lookback", 120))),
                S.rsi_extreme(s, tech, float(a.get("rsi_overbought", 75)),
                              float(a.get("rsi_oversold", 30))),
                S.ma_cross(s, tech),
            ):
                if det:
                    sigs.append(det)
            # stop/take-profit only for real-priced holdings (skip funds/certs
            # whose tracked-proxy price isn't their actual cost basis)
            h = hold_by_sym.get(s.symbol)
            if h is not None and h.fixed_value_sek is None and h.whole_share_instrument:
                sigs.extend(S.stop_take(s, h, stop_pct, tp_pct))
        res.emitted = _process(sigs, now, cfg)
        db.scan_run_finish(rid, n_scanned=res.scanned, n_signals=len(res.emitted), status="ok")
    except Exception as exc:  # pragma: no cover - defensive
        res.errors.append(str(exc))
        log.exception("intraday scan failed")
        db.scan_run_finish(rid, n_scanned=res.scanned, n_signals=0, status="error",
                           note=str(exc)[:200])
    return res


def run_full(kind: str = "full") -> ScanResult:
    cfg = get_config()
    a = cfg.get("engine.alerts", {}) or {}
    fx = get_fx_rates()
    db = get_db()
    rid = db.scan_run_start(kind)
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    res = ScanResult(kind=kind)
    try:
        uni, holdings, wl = _gather(cfg)
        entries = _dedup(uni + wl + [(h.ticker, h.exchange) for h in holdings])
        stocks = screen_data(entries)
        res.scanned = len(stocks)
        sigs: list[Signal] = []

        # technical signals across the whole batch
        for s in stocks:
            tech = compute_technicals(s)
            for det in (
                S.big_move(s, float(a.get("big_move_pct", 0.06)), today),
                S.breakout(s, int(a.get("breakout_lookback", 120))),
                S.rsi_extreme(s, tech, float(a.get("rsi_overbought", 75)),
                              float(a.get("rsi_oversold", 30))),
                S.ma_cross(s, tech),
            ):
                if det:
                    sigs.append(det)

        # rank price-only candidates, then pull fundamentals for the top slice
        scored = sorted(((s, analyze(s, fx, cfg=cfg).breakdown.composite) for s in stocks),
                        key=lambda x: x[1], reverse=True)
        top = [(s.ticker, s.exchange) for s, _ in scored[:25]]
        targets = _dedup(top + wl + [(h.ticker, h.exchange) for h in holdings])
        min_buy = float(a.get("new_buy_min_composite", 68))
        for ticker, exchange in targets:
            d = get_stock_data(ticker, exchange, enrich_news=False)
            rec = build_recommendation(d, fx, cfg=cfg)
            nb = S.new_buy(d, rec.score, rec.action, min_buy)
            if nb:
                sigs.append(nb)
            es = S.earnings_soon(d, int(a.get("earnings_within_days", 5)))
            if es:
                sigs.append(es)
            if rec.action == Action.BUY:
                res.top_buys.append(rec)

        # holdings review + action-change signals
        if holdings:
            from src.portfolio.opportunity_cost import analyze_portfolio

            review = analyze_portfolio(holdings, fx, cfg)
            res.holdings_review = review.holdings
            for ha in review.holdings:
                d = get_stock_data(ha.holding.ticker, ha.holding.exchange, enrich_news=False)
                ha_sig = S.holding_action(d, ha.action, ha.rationale, ha.trade_note)
                if ha_sig:
                    sigs.append(ha_sig)

        res.top_buys.sort(key=lambda r: r.score.composite, reverse=True)
        res.top_buys = res.top_buys[:8]
        res.emitted = _process(sigs, now, cfg)
        db.scan_run_finish(rid, n_scanned=res.scanned, n_signals=len(res.emitted), status="ok")
    except Exception as exc:  # pragma: no cover - defensive
        res.errors.append(str(exc))
        log.exception("%s scan failed", kind)
        db.scan_run_finish(rid, n_scanned=res.scanned, n_signals=0, status="error",
                           note=str(exc)[:200])
    return res


def run_scan(kind: str = "intraday", *, send: bool = True) -> ScanResult:
    """Run a scan and (optionally) dispatch notifications."""
    res = run_intraday() if kind == "intraday" else run_full(kind)
    if send:
        from src.engine.notify import dispatch_result

        dispatch_result(res)
    return res


def run_portfolio_pulse(*, send: bool = True) -> PulseResult:
    """Build a pulse on the user's ACTUAL portfolio — current actions with exact
    shares/SEK + the freshest screener BUY — and push it to Telegram/email.
    """
    cfg = get_config()
    db = get_db()
    rid = db.scan_run_start("pulse")
    res = PulseResult()
    try:
        holdings = db.portfolio_all()
        res.n_holdings = len(holdings)
        if holdings:
            from src.portfolio.opportunity_cost import analyze_portfolio

            review = analyze_portfolio(holdings, get_fx_rates(), cfg)
            res.value_sek = review.total_value_sek
            res.unrealized_pct = review.unrealized_pct
            res.actions = [h for h in review.holdings if h.action.value != "HOLD"]
            held = {h.holding.symbol for h in review.holdings}
            res.top_buys = [a for a in db.alerts_recent(80)
                            if a["type"] == "NEW_BUY" and a["symbol"] not in held][:2]
        db.scan_run_finish(rid, n_scanned=res.n_holdings, n_signals=len(res.actions), status="ok")
    except Exception as exc:  # pragma: no cover - defensive
        res.errors.append(str(exc))
        log.exception("portfolio pulse failed")
        db.scan_run_finish(rid, n_scanned=res.n_holdings, n_signals=0, status="error",
                           note=str(exc)[:200])
    if send:
        from src.engine.notify import dispatch_pulse

        dispatch_pulse(res)
    return res
