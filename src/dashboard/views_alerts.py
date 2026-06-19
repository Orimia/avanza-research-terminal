"""Dashboard page: Alerts & Engine — live signal feed, engine health, run-now."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.config import get_config
from src.dashboard import ui
from src.storage.db import get_db

_SEV = {"critical": "Critical", "warn": "Warning", "info": "Info"}


def page_alerts() -> None:
    cfg = get_config()
    st.header("Alerts & Engine")
    ui.disclaimer_banner()
    st.caption("The background engine scans SE/EU/US on a schedule and pushes new "
               "actionable signals to Telegram/email. This page is the same feed, "
               "plus a manual run.")

    db = get_db()

    # -- engine status -----------------------------------------------------
    last = db.last_scan_run()
    tg = "✅" if cfg.has_key("TELEGRAM_BOT_TOKEN") and cfg.has_key("TELEGRAM_CHAT_ID") else "—"
    em = "✅" if cfg.has_key("ALERT_EMAIL_SMTP_HOST") else "—"
    c = st.columns(4)
    c[0].metric("Engine enabled", "yes" if cfg.get("engine.enabled", True) else "no")
    c[1].metric("Scan interval", f"{cfg.get('engine.scan_interval_minutes', 20)} min")
    c[2].metric("Telegram", tg)
    c[3].metric("Email", em)
    if last:
        st.caption(f"Last scan: **{last['kind']}** at {last.get('started_at','?')} "
                   f"· status **{last.get('status','?')}** · "
                   f"{last.get('n_signals',0)} signal(s) from {last.get('n_scanned',0)} names")
    else:
        st.caption("No scan has run yet. Use **Run a scan now** below, or start the "
                   "engine: `python -m src.engine.scheduler`.")
    if tg == "—" and em == "—":
        st.warning("No alert channel configured — signals are still logged here, but "
                   "nothing is pushed. Set Telegram/email keys in `.env` to get pings.")

    # -- run now -----------------------------------------------------------
    st.subheader("Run a scan now")
    r1, r2, r3 = st.columns([1, 1, 2])
    do_full = r1.button("Full scan (digest)")
    do_intra = r2.button("Intraday scan")
    send = r3.toggle("Also push to Telegram/email", value=False,
                     help="Off = log + preview only. On = also send via configured channels.")
    if do_full or do_intra:
        from src.engine.notify import preview_text
        from src.engine.scanner import run_scan

        kind = "manual" if do_full else "intraday"
        with st.spinner(f"Running {kind} scan over SE/EU/US… (first run fetches live data)"):
            res = run_scan(kind, send=send)
        st.success(f"Scanned {res.scanned} names · {len(res.emitted)} new signal(s)"
                   + (" · pushed" if send else " · not pushed"))
        if res.errors:
            st.error("; ".join(res.errors))
        st.markdown("**Message preview:**")
        st.code(preview_text(res), language="text")

    # -- recent alerts feed ------------------------------------------------
    st.subheader("Recent signals")
    alerts = db.alerts_recent(300)
    if not alerts:
        st.info("No signals logged yet.")
    else:
        f1, f2, f3 = st.columns([1, 1, 1])
        sevs = f1.multiselect("Severity", ["critical", "warn", "info"],
                              default=["critical", "warn", "info"])
        types = sorted({a["type"] for a in alerts})
        pick_types = f2.multiselect("Type", types, default=types)
        query = f3.text_input("Filter symbol", "").strip().upper()
        rows = [a for a in alerts
                if a["severity"] in sevs and a["type"] in pick_types
                and (not query or query in a["symbol"].upper())]
        st.caption(f"{len(rows)} of {len(alerts)} signals")
        df = pd.DataFrame([{
            "When": a["created_at"][:16].replace("T", " "),
            "Sev": _SEV.get(a["severity"], "•"),
            "Symbol": a["symbol"], "Type": a["type"], "Action": a["action"],
            "Signal": a["title"], "Pushed": "✅" if a["sent"] else "—",
        } for a in rows])
        st.dataframe(df, width="stretch", hide_index=True, height=420)

    # -- scan history ------------------------------------------------------
    with st.expander("Scan history (engine health)"):
        runs = db.scan_runs_recent(25)
        if runs:
            st.dataframe(pd.DataFrame(runs), width="stretch", hide_index=True)
        else:
            st.caption("No runs recorded.")

    st.markdown("---")
    if st.toggle("Live auto-refresh (45s)", value=False):
        ui.autorefresh(45)
