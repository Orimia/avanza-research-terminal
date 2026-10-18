"""Format + dispatch engine output to Telegram / email, and log every alert.

Intraday scans send a single combined message (only when there are new signals,
so no spam). Digests always send a scheduled summary (top buys, holdings needing
attention, new signals). Every emitted signal is written to ``alerts_log`` so the
dashboard shows the same feed even if a channel is unconfigured.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.alerts.email import send_email
from src.alerts.telegram import send_telegram
from src.config import get_config
from src.engine.scanner import PulseResult, ScanResult
from src.engine.signals import Signal
from src.storage.db import get_db
from src.utils.logging import get_logger

log = get_logger("engine.notify")

_SEV_ICON = {"critical": "🔴", "warn": "🟠", "info": "🔵"}


def _footer() -> str:
    return f"— {get_config().disclaimer} · research only; place any orders yourself in Avanza."


def _plain(s: Signal) -> str:
    from src.reports.plain import translate_signal

    return translate_signal(s.type.value, s.action, s.symbol, s.title,
                            state=s.state_value, value=s.value)


def _format_intraday(res: ScanResult) -> tuple[str, str]:
    lines = [f"⚡ {len(res.emitted)} new signal(s) — Avanza Research"]
    for s in res.emitted:
        lines.append(f"{_SEV_ICON.get(s.severity, '•')} [{s.action}] {_plain(s)}")
    return "Avanza Research — intraday alerts", "\n".join(lines)


def _format_digest(res: ScanResult) -> tuple[str, str]:
    title = {"morning": "🌅 Morning digest", "close": "🌇 Post-close digest"}.get(
        res.kind, "📋 Digest")
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines = [f"{title} — Avanza Research Terminal ({day})", ""]
    if res.regime_note:
        lines.insert(1, f"🧭 {res.regime_note}")
    if res.kind == "morning":   # dead-man's switch: the engine reports on itself
        from datetime import timedelta

        yday = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
        runs = [r for r in get_db().scan_runs_recent(200)
                if (r.get("started_at") or "").startswith(yday)]
        errs = sum(1 for r in runs if r.get("status") == "error")
        lines.insert(2, f"🩺 Engine self-report: {len(runs)} scans yesterday, "
                        f"{errs} errors. If this line ever disappears, the engine is down.")

    if res.top_buys:
        lines.append(f"🟢 Top BUY candidates ({len(res.top_buys)}):")
        for r in res.top_buys:
            lines.append(f"  • {r.symbol} — score {r.score.composite:.0f} "
                         f"({r.confidence.value}); {r.main_reason}")
        lines.append("")

    acts = [h for h in res.holdings_review if h.action.value != "HOLD"]
    if acts:
        lines.append("⚠️ Holdings needing attention:")
        for h in acts:
            lines.append(f"  • {h.holding.symbol}: {h.action.value} — {h.rationale[:90]}")
        lines.append("")

    if res.emitted:
        lines.append(f"🔔 New signals today ({len(res.emitted)}):")
        for s in res.emitted:
            lines.append(f"  {_SEV_ICON.get(s.severity, '•')} [{s.action}] {_plain(s)}")
        lines.append("")

    if not (res.top_buys or acts or res.emitted):
        lines.append("No actionable changes right now. Sit tight.")
        lines.append("")

    lines.append("Open the dashboard for full memos & sizing.")
    subject = f"Avanza Research — {res.kind} digest {day}"
    return subject, "\n".join(lines)


def _send(subject: str, text: str, channels: list[str]) -> bool:
    body = f"{text}\n\n{_footer()}"
    ok = False
    if "telegram" in channels:
        ok = send_telegram(body) or ok
    if "email" in channels:
        ok = send_email(subject, body) or ok
    return ok


def _log(emitted: list[Signal], channels: list[str], sent: bool) -> None:
    db = get_db()
    chan = ",".join(channels)
    for s in emitted:
        db.alert_add(symbol=s.symbol, type=s.type.value, action=s.action,
                     severity=s.severity, title=s.title, detail=s.detail,
                     value=s.value, sent=sent, channels=chan)


def dispatch_result(res: ScanResult) -> bool:
    """Format + send notifications for a scan, and log emitted signals."""
    cfg = get_config()
    channels = list(cfg.get("engine.alerts.channels", ["telegram", "email"]))

    if res.kind == "intraday":
        if not res.emitted:
            return False  # nothing new — stay quiet
        subject, text = _format_intraday(res)
    else:
        subject, text = _format_digest(res)  # digests always send

    sent = _send(subject, text, channels)
    _log(res.emitted, channels, sent=sent)
    log.info("%s scan: %d emitted, sent=%s via %s",
             res.kind, len(res.emitted), sent, channels)
    return sent


_ACT_ICON = {"SELL": "🔴", "TRIM": "🟠", "BUY": "🟢", "HOLD": "⚪"}


def format_pulse(res: PulseResult) -> tuple[str, str]:
    day = datetime.now(timezone.utc).strftime("%b %d %H:%M")
    head = f"📊 Portfolio pulse · {day}"
    if not res.n_holdings:
        return head, f"{head}\nNo holdings loaded yet — add yours in the dashboard."
    val = f"{res.value_sek:,.0f} SEK"
    if res.unrealized_pct is not None:
        val += f"  ({res.unrealized_pct * 100:+.1f}% vs cost)"
    lines = [head, f"💼 {val}", ""]
    if res.regime_note:
        lines.insert(2, f"🧭 Regime: {res.regime_note}")
    if res.actions:
        lines.append(f"⚡ Act on your holdings ({len(res.actions)}):")
        for h in res.actions:
            lines.append(f"  {_ACT_ICON.get(h.action.value, '•')} {h.holding.ticker.upper()} — {h.trade_note}")
    else:
        lines.append("✅ Every holding rated HOLD — nothing to do right now.")
    if res.discipline:
        lines.append("")
        lines.append("🧠 Discipline check:")
        for m in res.discipline:
            lines.append(f"  • {m}")
    if res.top_buys:
        lines.append("")
        lines.append("🟢 Freshest screener idea(s):")
        for a in res.top_buys:
            lines.append(f"  • {a['title']}")
    return head, "\n".join(lines)


def dispatch_pulse(res: PulseResult) -> bool:
    """Push the portfolio pulse — but skip repeats: send when there's an action,
    when the action set changes, or once/day as a heartbeat (no all-HOLD spam)."""
    cfg = get_config()
    if not res.n_holdings:
        return False
    db = get_db()
    sig = "|".join(sorted(f"{h.holding.ticker}:{h.action.value}:{h.trade_shares}"
                          for h in res.actions)) or "ALL_HOLD"
    prior = db.signal_state_get("__pulse__")
    today = datetime.now(timezone.utc).date().isoformat()
    emitted_today = bool(prior and (prior.get("last_emitted") or "")[:10] == today)
    changed = (prior is None) or (prior.get("state_value") != sig)
    if not (res.actions or changed or not emitted_today):
        log.info("portfolio pulse: unchanged all-HOLD, already sent today — skipping")
        return False
    channels = list(cfg.get("engine.alerts.channels", ["telegram", "email"]))
    subject, text = format_pulse(res)
    sent = _send(subject, text, channels)
    if sent:
        db.signal_state_set("__pulse__", sig, touch_emitted=True)
    log.info("portfolio pulse: %d actions, sent=%s", len(res.actions), sent)
    return sent


# -- weekly portfolio letter (plain sentences, no jargon, no emoji) ---------- #
def build_weekly_letter(fetch=None) -> str:
    """Monday-morning letter: each holding this week vs your cost, best and
    worst, and what (if anything) to do. Full sentences, human-readable."""
    from src.data.fx_client import get_fx_rates
    from src.data.provider import get_stock_data
    from src.portfolio.opportunity_cost import analyze_portfolio
    from src.reports.plain import action_sentence, first_sentence
    from src.scoring.regime import current_regime

    fetch = fetch or get_stock_data
    cfg = get_config()
    db = get_db()
    holdings = db.portfolio_all()
    if not holdings:
        return "No holdings loaded yet — add your portfolio in the dashboard."
    fx = get_fx_rates()

    rows = []
    for h in holdings:
        try:
            d = fetch(h.ticker, h.exchange, enrich_news=False)
        except Exception:
            continue
        closes = d.closes()
        if d.is_mock or len(closes) < 6:
            continue
        week = closes[-1] / closes[-6] - 1.0
        since = (closes[-1] / h.average_cost - 1.0) if h.average_cost else None
        rows.append({"name": d.display_name, "ticker": h.ticker.upper(),
                     "week": week, "since": since})
    lines = ["Your weekly portfolio letter", ""]
    reg = current_regime(cfg=cfg)
    if reg.is_known:
        mood = {"risk-on": "Markets are in a risk-on phase — conditions favor quality buys.",
                "risk-off": "Markets are defensive right now — the engine demands more "
                            "proof before calling anything a buy.",
                "neutral": "Markets are in a neutral phase — no strong tailwind either way."}
        lines += [mood.get(reg.label, ""), ""]
    if rows:
        avg_week = sum(r["week"] for r in rows) / len(rows)
        lines.append(f"Your holdings moved {avg_week * 100:+.1f}% on average this week.")
        best = max(rows, key=lambda r: r["week"])
        worst = min(rows, key=lambda r: r["week"])
        lines.append(f"Best: {best['name']} ({best['ticker']}) {best['week'] * 100:+.1f}% "
                     "this week.")
        lines.append(f"Worst: {worst['name']} ({worst['ticker']}) "
                     f"{worst['week'] * 100:+.1f}% this week.")
        lines.append("")
        lines.append("Where you stand versus what you paid:")
        for r in sorted(rows, key=lambda r: -(r["since"] or -9)):
            if r["since"] is not None:
                lines.append(f"  {r['ticker']}: {r['since'] * 100:+.0f}% since you bought"
                             f" ({r['week'] * 100:+.1f}% this week)")
        lines.append("")
    try:
        from src.reports.plain import discipline_by_symbol

        review = analyze_portfolio(holdings, fx, cfg)
        cautions = discipline_by_symbol(review, cfg)
        acts = [h for h in review.holdings if h.action.value not in ("HOLD",)]
        if acts:
            lines.append("What to do this week:")
            for ha in acts[:4]:
                d = fetch(ha.holding.ticker, ha.holding.exchange, enrich_news=False)
                lines.append("  " + action_sentence(
                    ha, first_sentence(d.description, 110),
                    caution=cautions.get(ha.holding.ticker.upper())))
        else:
            lines.append("Nothing to do this week — every holding is rated HOLD. "
                         "Doing nothing is a position, and this week it is the right one.")
    except Exception:  # pragma: no cover - letter must never crash on review
        log.exception("weekly letter review failed")
    closed = [p for p in get_db().paper_positions("closed")]
    if closed:
        pnl = sum(float(p["pnl_sek"] or 0) for p in closed)
        lines += ["", f"Engine track record so far: {len(closed)} closed paper trades, "
                      f"{pnl:+,.0f} kr total."]
    return "\n".join(lines)


def send_weekly_letter() -> bool:
    cfg = get_config()
    channels = list(cfg.get("engine.alerts.channels", ["telegram", "email"]))
    text = build_weekly_letter()
    sent = _send("Your weekly portfolio letter", text, channels)
    log.info("weekly letter sent=%s", sent)
    return sent


def send_test() -> bool:
    """Send a test alert to all configured channels (for setup verification)."""
    cfg = get_config()
    channels = list(cfg.get("engine.alerts.channels", ["telegram", "email"]))
    text = ("✅ Avanza Research Terminal — test alert.\nThis channel works; you'll receive "
            "BUY / TRIM / SELL signals and daily digests here.")
    ok = _send("Avanza Research — test alert", text, channels)
    log.info("test alert sent=%s via %s", ok, channels)
    return ok


def preview_text(res: ScanResult) -> str:
    """Return the message body without sending (for --dry-run / dashboard)."""
    if res.kind == "intraday":
        _, text = _format_intraday(res)
    else:
        _, text = _format_digest(res)
    return f"{text}\n\n{_footer()}"
