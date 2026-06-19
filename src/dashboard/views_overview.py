"""Overview / Today — the glanceable home: market + engine status, today's
BUY ideas, latest signals, and a holdings snapshot. Reads mostly from the DB
(fast) so it can auto-refresh while the engine works in the background.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from src.config import get_config
from src.dashboard import ui
from src.engine.market_hours import open_markets
from src.storage.db import get_db


def _ago(iso: str | None) -> str:
    if not iso:
        return "never"
    try:
        t = datetime.fromisoformat(iso)
    except ValueError:
        return "?"
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    mins = (datetime.now(timezone.utc) - t).total_seconds() / 60
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{int(mins)}m ago"
    if mins < 1440:
        return f"{int(mins / 60)}h ago"
    return f"{int(mins / 1440)}d ago"


def _open_deep_dive(ticker: str, exchange: str) -> None:
    st.session_state["dd_ticker"] = ticker
    st.session_state["dd_exchange"] = exchange
    st.session_state["page"] = "Stock Deep Dive"
    st.rerun()


def page_overview() -> None:
    cfg = get_config()
    db = get_db()

    # header row: title + market chips
    hl, hr = st.columns([2, 3])
    hl.markdown("# Today")
    hr.markdown(f"<div style='text-align:right;padding-top:18px'>{ui.market_status_chips()}</div>",
                unsafe_allow_html=True)
    ui.disclaimer_banner()

    # data snapshot
    today0 = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    todays = db.alerts_since(today0.isoformat())
    new_buys = [a for a in todays if a["type"] == "NEW_BUY"]
    last = db.last_scan_run()
    holdings = db.portfolio_all()

    # KPI row
    k = st.columns(4)
    k[0].metric("Markets open", f"{len(open_markets(cfg.get('engine.scope', [])))}/3")
    k[1].metric("Engine last scan", _ago(last["started_at"]) if last else "never",
                help=(f"{last['kind']} · {last.get('status','?')}" if last else
                      "Start it: python -m src.engine.scheduler"))
    k[2].metric("New BUY signals today", len(new_buys))
    k[3].metric("Signals today", len(todays))

    st.markdown("")
    left, right = st.columns([3, 2])

    # -- left: today's BUY ideas / what to do --------------------------------
    with left:
        st.subheader("What to do today")
        actionable = [a for a in todays
                      if a["type"] in ("NEW_BUY", "HOLDING_ACTION", "STOP_HIT", "TAKEPROFIT_HIT")]
        if not actionable:
            st.info("No new actionable signals yet today. The engine scans during market "
                    "hours; you can also run a scan from **Alerts & Engine**.")
        for a in actionable[:8]:
            with st.container(border=True):
                c = st.columns([3, 1])
                c[0].markdown(f"{ui.sev_dot(a['severity'])}{ui.action_badge(a['action'])} "
                              f"&nbsp; **{a['symbol']}**  \n"
                              f"<span style='color:#8b98a9;font-size:0.85rem'>{a['title']}</span>",
                              unsafe_allow_html=True)
                if c[1].button("Deep dive", key=f"ov_{a['symbol']}_{a['created_at']}"):
                    tk, ex = a["symbol"].rsplit(".", 1)
                    _open_deep_dive(tk, ex)

    # -- right: latest signal feed ------------------------------------------
    with right:
        st.subheader("Latest signals")
        recent = db.alerts_recent(12)
        if not recent:
            st.caption("No signals logged yet.")
        for a in recent:
            st.markdown(
                f"<div style='padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.06)'>"
                f"{ui.sev_dot(a['severity'])}<b>{a['symbol']}</b> "
                f"<span style='color:#8b98a9'>· {a['type'].replace('_', ' ').lower()}</span><br>"
                f"<span style='font-size:0.82rem;color:#c4cdd9'>{a['title']}</span> "
                f"<span style='float:right;color:#6b7787;font-size:0.75rem'>{_ago(a['created_at'])}</span>"
                f"</div>", unsafe_allow_html=True)

    # -- holdings snapshot ---------------------------------------------------
    if holdings:
        st.markdown("")
        st.subheader("Holdings snapshot")
        with st.spinner("Valuing holdings…"):
            from src.portfolio.opportunity_cost import analyze_portfolio

            review = analyze_portfolio(holdings, ui.load_fx())
        m = st.columns(3)
        m[0].metric("Portfolio value (SEK)", f"{review.total_value_sek:,.0f}")
        if review.unrealized_pct is not None:
            m[1].metric("Unrealized", f"{review.unrealized_pct * 100:+.1f}%")
        m[2].metric("Top concentration", f"{review.concentration_top:.1f}%")
        flagged = [h for h in review.holdings if h.action.value != "HOLD"]
        if flagged:
            st.dataframe(pd.DataFrame([{
                "Symbol": h.holding.symbol, "Action": h.action.value,
                "Score": round(h.score.composite, 0) if h.score else None,
                "Weight %": h.weight_pct, "Why": h.rationale,
            } for h in flagged]), width="stretch", hide_index=True)
        else:
            st.caption("All holdings rated HOLD — nothing to act on.")

    # -- live auto-refresh ---------------------------------------------------
    st.markdown("---")
    refresh = st.toggle("Live auto-refresh (60s)", value=True,
                        help="Reloads this page so new engine signals appear automatically.")
    if refresh:
        ui.autorefresh(60)
