"""Overview — a dense, professional command center: market tape with
sparklines, KPI strip, live holdings grid, today's ideas, tagged signal feed.
Reads from the warm data cache + DB so it stays fast and auto-refreshable.
"""
from __future__ import annotations

from datetime import datetime, timezone

import streamlit as st

from src.config import get_config
from src.dashboard import ui
from src.data.provider import get_stock_data
from src.engine.market_hours import open_markets
from src.storage.db import get_db
from src.utils.currency import to_sek

_TYPE_TAG = {
    "NEW_BUY": ("BUY", ui.GREEN), "HOLDING_ACTION": ("ACT", ui.AMBER),
    "STOP_HIT": ("STOP", ui.RED), "TAKEPROFIT_HIT": ("TAKE", ui.GREEN),
    "BIG_MOVE": ("MOVE", ui.AMBER), "BREAKOUT": ("BRK", ui.BLUE),
    "RSI_EXTREME": ("RSI", ui.BLUE), "MA_CROSS": ("MA", ui.MUTED),
    "EARNINGS_SOON": ("EARN", ui.AMBER),
}
_ACT_COLOR = {"BUY": ui.GREEN, "SELL": ui.RED, "TRIM": ui.AMBER,
              "HOLD": ui.MUTED, "WATCH": ui.AMBER, "REVIEW": ui.BLUE}


def _ago(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return "—"
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    m = (datetime.now(timezone.utc) - t).total_seconds() / 60
    if m < 1:
        return "now"
    if m < 60:
        return f"{int(m)}m"
    if m < 2880:
        return f"{int(m / 60)}h"
    return f"{int(m / 1440)}d"


def _pcolor(x: float | None) -> str:
    if x is None:
        return ui.MUTED
    return ui.GREEN if x > 0 else ui.RED if x < 0 else ui.MUTED


def _pct(x: float | None, dp: int = 1) -> str:
    if x is None:
        return "<span style='color:#8e8e93'>—</span>"
    if round(x * 100, dp) == 0:            # flat -> neutral gray, no "-0.0%"
        return f"<span style='color:{ui.MUTED}'>{0:.{dp}f}%</span>"
    return f"<span style='color:{_pcolor(x)}'>{x * 100:+.{dp}f}%</span>"


def _day_pct(data) -> float | None:
    c = data.closes()
    if len(c) < 2 or c[-2] <= 0 or data.is_mock:
        return None
    return c[-1] / c[-2] - 1.0


# -- cached payloads --------------------------------------------------------- #
@st.cache_data(ttl=300, show_spinner=False)
def _bench(sym: str, label: str):
    try:
        d = get_stock_data(sym, "US", enrich_news=False)
    except Exception:
        return None
    if d.is_mock or len(d.price_history) < 30:
        return None
    closes = d.closes()
    base = closes[-64] if len(closes) >= 64 else closes[0]
    return {"label": label, "day": _day_pct(d), "ret3m": closes[-1] / base - 1.0,
            "spark": closes[-64:]}


@st.cache_data(ttl=300, show_spinner="Valuing portfolio…")
def _portfolio_rows():
    fx_local = ui.load_fx()
    rows, total = [], 0.0
    for h in get_db().portfolio_all():
        try:
            d = get_stock_data(h.ticker, h.exchange, enrich_news=False)
        except Exception:
            continue
        px = d.quote.price if d.quote else None
        val = h.fixed_value_sek if h.fixed_value_sek is not None else (
            to_sek(px, h.currency, fx_local) * h.shares if px else 0.0)
        since = None   # before vs now: what you paid vs today's price
        if px and h.average_cost and h.fixed_value_sek is None and not d.is_mock:
            since = px / h.average_cost - 1.0
        rows.append({"ticker": h.ticker.upper(), "kind": h.kind,
                     "px": px, "ccy": h.currency, "day": _day_pct(d),
                     "since": since, "cost": h.average_cost or None,
                     "val": val or 0.0, "mock": d.is_mock})
        total += val or 0.0
    rows.sort(key=lambda r: r["val"], reverse=True)
    day_pnl = sum((r["day"] or 0) * r["val"] for r in rows)
    return rows, total, day_pnl


@st.cache_data(ttl=600, show_spinner="Working out what to do…")
def _decisions():
    """Concrete plain-language actions on YOUR holdings + the freshest idea."""
    from src.data.fx_client import get_fx_rates
    from src.portfolio.opportunity_cost import analyze_portfolio
    from src.reports.plain import action_sentence, discipline_by_symbol, first_sentence

    holdings = get_db().portfolio_all()
    if not holdings:
        return [], None
    try:
        review = analyze_portfolio(holdings, get_fx_rates())
    except Exception:
        return [], None
    cautions = discipline_by_symbol(review)
    out = []
    for ha in review.holdings:
        if ha.action.value == "HOLD":
            continue
        try:
            d = get_stock_data(ha.holding.ticker, ha.holding.exchange, enrich_news=False)
            brief = first_sentence(d.description, 110)
        except Exception:
            brief = None
        out.append({"action": ha.action.value,
                    "text": action_sentence(ha, brief,
                                            caution=cautions.get(ha.holding.ticker.upper()))})
    # freshest screener idea, with a brief so it means something
    idea = None
    for a in get_db().alerts_recent(120):
        if a["type"] == "NEW_BUY":
            tk, ex = a["symbol"].rsplit(".", 1)
            try:
                d = get_stock_data(tk, ex, enrich_news=False)
                brief = first_sentence(d.description, 130) or ""
                score = f" Engine score {a['value']:.0f}/100." if a.get("value") else ""
                idea = {"symbol": a["symbol"], "name": d.display_name,
                        "text": f"{d.display_name} ({tk.upper()}) — {brief}{score}"}
            except Exception:
                idea = {"symbol": a["symbol"], "name": a["symbol"], "text": a["title"]}
            break
    return out, idea


# -- sections ----------------------------------------------------------------- #
def _tape() -> None:
    cfg = get_config()
    items = []
    for sym, label in (("^GSPC", "S&P 500"), ("^OMX", "OMXS30")):
        b = _bench(sym, label)
        if b:
            items.append(f"<span class='tape-item'><span class='tl'>{b['label']}</span>"
                         f"<span class='tv'>{_pct(b['day'])}</span>"
                         f"<span class='sub'>3m {_pct(b['ret3m'], 0)}</span></span>")
    n_open = len(open_markets(cfg.get("engine.scope", [])))
    mkts = f"<span class='tape-item'><span class='tl'>Markets</span><span class='tv'>{n_open}/3 open</span></span>"
    reg = ui.load_regime()
    rc = ui._REGIME_COLOR.get(reg["label"], ui.MUTED)
    chip = (f"<span class='tag' style='background:{rc}1c;color:{rc};border:0.5px solid {rc}55;"
            f"font-size:10.5px;padding:2px 10px'>Regime · {reg['label']}</span>")
    left, right = st.columns([4, 2])
    left.markdown(f"<div style='padding-top:4px'>{''.join(items)}{mkts}</div>",
                  unsafe_allow_html=True)
    right.markdown(f"<div style='text-align:right;padding-top:3px'>{chip}</div>",
                   unsafe_allow_html=True)


def _kpis(rows, total, day_pnl) -> None:
    db = get_db()
    today0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    todays = db.alerts_since(today0.isoformat())
    buys = [a for a in todays if a["type"] == "NEW_BUY"]
    paper = db.paper_positions()
    realized = sum(float(p["pnl_sek"] or 0) for p in paper if p["status"] == "closed")
    last = db.last_scan_run()
    k = st.columns(6)
    k[0].metric("Portfolio", f"{total:,.0f} kr",
                help="Everything you own, valued at live prices, in Swedish kronor.")
    k[1].metric("Day P&L", f"{day_pnl:+,.0f} kr",
                delta=f"{day_pnl / total * 100:+.2f}%" if total else None,
                help="How much your holdings gained or lost today, in kronor.")
    k[2].metric("Signals today", len(todays),
                help="Everything the engine noticed today — most need no action.")
    k[3].metric("New BUYs", len(buys),
                help="Stocks that newly cleared the engine's buy bar today.")
    k[4].metric("Paper P&L", f"{realized:+,.0f} kr",
                help="The engine trades its own calls on paper (never real money). "
                     "This is its realized profit — its honest track record.")
    k[5].metric("Last scan", _ago(last["started_at"]) if last else "never",
                help="How long ago the engine last checked the market. "
                     f"Kind: {(last or {}).get('kind', '—')}")


def _holdings_panel(rows, total) -> None:
    st.markdown(ui.panel_header("Portfolio", f"{len(rows)} positions"), unsafe_allow_html=True)
    if not rows:
        st.caption("No holdings loaded — add yours in Portfolio Review.")
        return
    body = ""
    for r in rows[:14]:
        w = r["val"] / total * 100 if total else 0
        px = f"{r['px']:,.2f}" if r["px"] else "—"
        cost = f"{r['cost']:,.0f}" if r.get("cost") else "—"
        body += (f"<tr><td><span class='sym'>{r['ticker']}</span> "
                 f"<span class='sub'>{r['kind']}</span></td>"
                 f"<td>{px}</td><td>{_pct(r['day'])}</td>"
                 f"<td><span class='sub'>{cost}</span></td><td>{_pct(r.get('since'), 0)}</td>"
                 f"<td>{r['val']:,.0f}</td><td>{w:.1f}%</td></tr>")
    st.markdown(
        "<table class='term'><tr><th>Name</th><th>Px</th><th>Day</th>"
        f"<th>Paid</th><th>Since buy</th><th>Value kr</th><th>Wt</th></tr>{body}</table>",
        unsafe_allow_html=True)
    if len(rows) > 14:
        st.caption(f"+{len(rows) - 14} smaller positions — full detail in Portfolio Review.")


def _today_panel() -> None:
    db = get_db()
    st.markdown(ui.panel_header("What to do", datetime.now().strftime("%b %d")),
                unsafe_allow_html=True)
    decisions, idea = _decisions()
    if decisions:
        for d in decisions[:5]:
            c = _ACT_COLOR.get(d["action"], ui.MUTED)
            st.markdown(f"<div class='feed-row'>{ui.tag(d['action'], c)}"
                        f"<span style='font-size:12.5px;color:#1d1d1f'>{d['text']}</span></div>",
                        unsafe_allow_html=True)
    else:
        st.markdown("<div class='feed-row'><span class='sub'>Nothing to change in your "
                    "portfolio — every holding is currently a HOLD. Doing nothing is "
                    "also a decision, and today it is the right one.</span></div>",
                    unsafe_allow_html=True)
    if idea:
        st.markdown(ui.panel_header("Freshest buy idea"), unsafe_allow_html=True)
        st.markdown(f"<div class='feed-row'>{ui.tag('BUY', ui.GREEN)}"
                    f"<span style='font-size:12.5px;color:#1d1d1f'>{idea['text']}</span></div>",
                    unsafe_allow_html=True)

    today0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    todays = db.alerts_since(today0.isoformat())
    acts = [a for a in todays if a["type"] in
            ("NEW_BUY", "HOLDING_ACTION", "STOP_HIT", "TAKEPROFIT_HIT")]
    if acts:
        st.markdown(ui.panel_header("Today's signals"), unsafe_allow_html=True)
        for a in acts[:4]:
            t, c = _TYPE_TAG.get(a["type"], ("SIG", ui.MUTED))
            st.markdown(f"<div class='feed-row'>{ui.tag(t, c)}"
                        f"<span class='sym'>{a['symbol']}</span><br>"
                        f"<span class='sub'>{a['title']}</span></div>",
                        unsafe_allow_html=True)


def _feed_panel() -> None:
    st.markdown(ui.panel_header("Signal feed", "live"), unsafe_allow_html=True)
    recent = get_db().alerts_recent(14)
    if not recent:
        st.caption("No signals logged yet.")
        return
    for a in recent:
        t, c = _TYPE_TAG.get(a["type"], ("SIG", ui.MUTED))
        act = a.get("action") or ""
        act_html = (f" <span style='color:{_ACT_COLOR.get(act, ui.MUTED)};font-size:10.5px;"
                    f"font-weight:650'>{act}</span>") if act else ""
        st.markdown(f"<div class='feed-row'>{ui.tag(t, c)}"
                    f"<span class='sym'>{a['symbol']}</span>{act_html}"
                    f"<span class='ago'>{_ago(a['created_at'])}</span><br>"
                    f"<span class='sub'>{a['title']}</span></div>",
                    unsafe_allow_html=True)


def _vs_index_panel() -> None:
    """The one chart that matters: your portfolio vs just buying the index,
    from the day tracking started. No back-filled history, no pretending."""
    snaps = get_db().snapshots()
    st.markdown(ui.panel_header("You vs the index",
                                f"since {snaps[0]['day']}" if snaps else ""),
                unsafe_allow_html=True)
    if len(snaps) < 2:
        st.caption("Tracking started "
                   f"{snaps[0]['day'] if snaps else 'today'} — this chart compares your "
                   "portfolio against simply buying the index, and it builds one point "
                   "per day. Come back in a week.")
        return
    import plotly.graph_objects as go
    days = [s["day"][5:] for s in snaps]
    fig = go.Figure()
    series = [("You", [s["value_sek"] for s in snaps], ui.BLUE, 2.4),
              ("S&P 500", [s["spx"] for s in snaps], ui.MUTED, 1.4),
              ("OMXS30", [s["omx"] for s in snaps], ui.AMBER, 1.4)]
    for name, vals, color, width in series:
        if not all(v for v in vals):
            continue
        norm = [v / vals[0] * 100 for v in vals]
        fig.add_trace(go.Scatter(x=days, y=norm, name=name, mode="lines",
                                 line=dict(color=color, width=width)))
    ui._dark(fig, 210)
    fig.update_layout(yaxis_title="Indexed to 100")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    you = snaps[-1]["value_sek"] / snaps[0]["value_sek"] - 1
    parts = [f"You {you * 100:+.1f}%"]
    if snaps[0]["spx"] and snaps[-1]["spx"]:
        parts.append(f"S&P 500 {(snaps[-1]['spx'] / snaps[0]['spx'] - 1) * 100:+.1f}%")
    if snaps[0]["omx"] and snaps[-1]["omx"]:
        parts.append(f"OMXS30 {(snaps[-1]['omx'] / snaps[0]['omx'] - 1) * 100:+.1f}%")
    st.caption(" · ".join(parts) + " since tracking began. If the index beats you "
               "over months, the honest answer is an index fund.")


def _benchmarks_panel() -> None:
    st.markdown(ui.panel_header("Markets", "3 months"), unsafe_allow_html=True)
    shown = False
    for sym, label in (("^GSPC", "S&P 500"), ("^OMX", "OMXS30")):
        b = _bench(sym, label)
        if not b:
            continue
        shown = True
        st.markdown(f"<span class='sub'>{label}</span> "
                    f"<span class='sym'>{_pct(b['ret3m'])}</span>", unsafe_allow_html=True)
        st.plotly_chart(ui.sparkline(b["spark"]), width="stretch",
                        config={"displayModeBar": False}, key=f"spark_{sym}")
    if not shown:
        st.caption("Benchmark data unavailable (offline).")


def page_overview() -> None:
    hl, hr = st.columns([2, 4])
    hl.markdown("# Overview")
    with hr:
        _tape()
    ui.disclaimer_banner()

    rows, total, day_pnl = _portfolio_rows()
    _kpis(rows, total, day_pnl)

    if ui.is_simple():
        # Simple mode: your money and what to do about it — nothing else.
        left, right = st.columns([5, 5])
        with left:
            with st.container(border=True):
                _holdings_panel(rows, total)
            with st.container(border=True):
                _vs_index_panel()
        with right, st.container(border=True):
            _today_panel()
    else:
        left, mid, right = st.columns([5, 4, 4])
        with left:
            with st.container(border=True):
                _holdings_panel(rows, total)
            with st.container(border=True):
                _vs_index_panel()
        with mid, st.container(border=True):
            _today_panel()
        with right:
            with st.container(border=True):
                _feed_panel()
            with st.container(border=True):
                _benchmarks_panel()

    if st.toggle("Live auto-refresh (60s)", value=True,
                 help="Reloads so new engine signals appear automatically."):
        ui.autorefresh(60)
