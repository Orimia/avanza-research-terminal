"""Dashboard pages: Portfolio Review, Risk Dashboard, Settings."""
from __future__ import annotations


import pandas as pd
import streamlit as st

from src.config import PROJECT_ROOT, get_config, reload_config
from src.dashboard import ui
from src.data.provider import get_stock_data
from src.models.schemas import Holding
from src.portfolio.import_avanza_csv import parse_any
from src.portfolio.opportunity_cost import analyze_portfolio, find_replacements, opportunity_cost
from src.scoring.technicals import compute_technicals
from src.storage.db import get_db
from src.utils.logging import read_network_log


def _ensure_holdings() -> list:
    if "holdings" not in st.session_state:
        db_holdings = get_db().portfolio_all()
        if db_holdings:
            st.session_state["holdings"] = db_holdings
    return st.session_state.get("holdings", [])


_COLS = ["ticker", "exchange", "shares", "average_cost", "currency", "sector", "notes"]


def _holdings_to_df(holdings: list) -> pd.DataFrame:
    if not holdings:
        return pd.DataFrame(columns=_COLS)
    return pd.DataFrame([{
        "ticker": h.ticker, "exchange": h.exchange, "shares": h.shares,
        "average_cost": h.average_cost, "currency": h.currency,
        "sector": h.sector or "", "notes": h.notes or "",
    } for h in holdings])


def _df_to_holdings(df: pd.DataFrame) -> list:
    out = []
    for _, row in df.iterrows():
        tk = str(row.get("ticker", "") or "").strip()
        if not tk:
            continue
        try:
            out.append(Holding(
                ticker=tk.upper(),
                exchange=(str(row.get("exchange", "ST") or "ST").strip().upper() or "ST"),
                shares=float(row.get("shares") or 0),
                average_cost=float(row.get("average_cost") or 0),
                currency=(str(row.get("currency", "SEK") or "SEK").strip().upper() or "SEK"),
                sector=(str(row.get("sector", "") or "").strip() or None),
                notes=(str(row.get("notes", "") or "").strip() or None),
            ))
        except (ValueError, TypeError):
            continue
    return out


def _save(holdings: list) -> None:
    st.session_state["holdings"] = holdings
    get_db().portfolio_replace(holdings)


def _holdings_manager() -> list:
    holdings = _ensure_holdings()
    with st.expander("📥 Manage holdings — import Avanza CSV · paste · edit",
                     expanded=not holdings):
        t_edit, t_file, t_paste, t_sample = st.tabs(
            ["✏️ Editor", "📄 Import file", "📋 Paste", "🧪 Sample"])
        with t_edit:
            st.caption("Add/edit rows directly (exchange: ST / US / EU / CO / OL), then Save. "
                       "This is your live holdings — analysis updates from here.")
            edited = st.data_editor(_holdings_to_df(holdings), num_rows="dynamic",
                                    width="stretch", key="hold_editor")
            if st.button("Save holdings", type="primary"):
                _save(_df_to_holdings(edited))
                st.success("Saved.")
                st.rerun()
        with t_file:
            st.caption("Drop your **Avanza CSV export** (Exportera) or the native format. "
                       "Auto-detected; then review/fix in the Editor tab.")
            up = st.file_uploader("CSV", type=["csv", "txt"], key="hold_up")
            if up is not None:
                try:
                    hs, fmt = parse_any(up.getvalue().decode("utf-8", "ignore"))
                    if hs:
                        _save(hs)
                        st.success(f"Imported {len(hs)} holdings ({fmt}). Review in Editor.")
                        st.rerun()
                    else:
                        st.error("No holdings parsed — check the file or use the Editor.")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Import failed: {exc}")
        with t_paste:
            txt = st.text_area("One per line: TICKER SHARES AVGCOST [EXCHANGE] [CCY]",
                               height=130, placeholder="VOLV-B 40 245\nNVDA 8 95 US USD")
            if st.button("Parse & save") and txt.strip():
                hs, fmt = parse_any(txt)
                if hs:
                    _save(hs)
                    st.success(f"Saved {len(hs)} holdings ({fmt}).")
                    st.rerun()
                else:
                    st.error("Couldn't parse — use 'TICKER SHARES AVGCOST'.")
        with t_sample:
            if st.button("Load sample portfolio"):
                hs, _ = parse_any((PROJECT_ROOT / "examples" / "sample_portfolio.csv").read_text())
                _save(hs)
                st.rerun()
    return _ensure_holdings()


def _action_plan(review, repl: list) -> None:
    st.subheader("Action plan — add / cut / replace")
    adds = [h for h in review.holdings if h.action.value == "BUY"]
    cuts = [h for h in review.holdings if h.action.value in ("SELL", "TRIM")]
    weakest = review.weakest()
    cols = st.columns(3)
    with cols[0]:
        st.markdown("##### 🟢 ADD")
        for h in adds:
            st.markdown(f"- **{h.holding.ticker.upper()}** → {h.trade_note}")
        for r in repl[:3]:
            sz = f" — buy ~{r.sizing.shares} sh" if r.sizing else ""
            up = (f" · analyst {r.analyst_upside * 100:+.0f}%"
                  if r.analyst_upside is not None else "")
            st.markdown(f"- **{r.ticker.upper()}** (new) score {r.score.composite:.0f}{sz}{up}")
        if not adds and not repl:
            st.caption("Nothing compelling to add right now.")
    with cols[1]:
        st.markdown("##### 🔴 CUT")
        if cuts:
            for h in cuts:
                st.markdown(f"- **{h.holding.ticker.upper()}** → **{h.trade_note}**  \n"
                            f"<span style='color:#8b98a9;font-size:0.8rem'>{h.rationale[:64]}</span>",
                            unsafe_allow_html=True)
        else:
            st.caption("No cuts — all holdings rated HOLD/BUY.")
    with cols[2]:
        st.markdown("##### 🔁 REPLACE")
        if weakest and repl and repl[0].score.composite > (weakest.score.composite + 8):
            st.markdown(f"- Swap weakest **{weakest.holding.ticker.upper()}** "
                        f"({weakest.score.composite:.0f}) → **{repl[0].ticker.upper()}** "
                        f"({repl[0].score.composite:.0f})")
            for v in opportunity_cost(repl[0].score, weakest).values():
                st.caption(f"• {v}")
        else:
            st.caption("No clearly better replacement than current holdings.")


# ============================== Portfolio Review ========================== #
def page_portfolio() -> None:
    cfg = get_config()
    st.header("Portfolio Review")
    ui.disclaimer_banner()
    st.caption("Live analysis of **your** holdings (you sync them manually — no Avanza "
               "login). Prices, scores and add/cut/replace update in real time.")

    holdings = _holdings_manager()
    if not holdings:
        st.info("Add your holdings above to get live add/cut/replace suggestions.")
        return

    fx = ui.load_fx()
    review = analyze_portfolio(holdings, fx)
    pv = ui.portfolio_value(cfg.portfolio_value_sek)
    held = {h.holding.symbol for h in review.holdings}
    pool = []
    for region in ("nordic", "us"):  # most relevant for replacements; EU on the Screener
        recs, _ = ui.unpack_recs(ui.run_screen(region, False, pv))
        pool.extend(recs)
    repl = find_replacements(pool, held)

    m = st.columns(4)
    m[0].metric("Total value (SEK)", f"{review.total_value_sek:,.0f}")
    if review.unrealized_pct is not None:
        m[1].metric("Unrealized", f"{review.unrealized_pct * 100:+.1f}%")
    m[2].metric("Concentration (top)", f"{review.concentration_top:.1f}%")
    m[3].metric("Holdings", len(review.holdings))

    _action_plan(review, repl)

    st.subheader("Per-holding decisions — with exact trade")
    df = pd.DataFrame([{
        "Ticker": h.holding.ticker.upper(), "Name": h.name or h.holding.ticker.upper(),
        "Kind": h.holding.kind, "Action": h.action.value,
        "Do this": h.trade_note,
        "Score": round(h.score.composite) if h.score else None,
        "Weight %": h.weight_pct,
        "Analyst ▲%": round(h.analyst_upside * 100, 1) if h.analyst_upside is not None else None,
        "Value SEK": round(h.value_sek) if h.value_sek else None,
    } for h in review.holdings])
    st.dataframe(df, width="stretch", hide_index=True)

    st.markdown("---")
    if st.toggle("Live auto-refresh (60s)", value=False):
        ui.autorefresh(60)


# ============================== Risk Dashboard ============================ #
def page_risk() -> None:
    st.header("Risk Dashboard")
    ui.disclaimer_banner()
    holdings = _ensure_holdings()
    if not holdings:
        st.info("Load a portfolio in Portfolio Review first.")
        return

    fx = ui.load_fx()
    review = analyze_portfolio(holdings, fx)
    tv = review.total_value_sek or 1.0

    e = st.columns(3)
    e[0].plotly_chart(ui.exposure_pie(review.country_exposure, "Country %"), width="stretch")
    e[1].plotly_chart(ui.exposure_pie(review.currency_exposure, "Currency %"), width="stretch")
    e[2].plotly_chart(ui.exposure_pie(review.sector_exposure, "Sector %"), width="stretch")

    # weighted volatility / drawdown proxy
    from src.scoring.risk import max_drawdown

    wv = wdd = 0.0
    for h in review.holdings:
        w = (h.value_sek or 0) / tv
        data = get_stock_data(h.holding.ticker, h.holding.exchange)
        t = compute_technicals(data)
        wv += w * (t.volatility or 0.0)
        wdd += w * (max_drawdown(data.closes()) or 0.0)

    k = st.columns(4)
    k[0].metric("Concentration top", f"{review.concentration_top:.1f}%")
    k[1].metric("HHI", f"{review.hhi:.3f}")
    k[2].metric("Vol proxy (ann.)", f"{wv*100:.0f}%")
    k[3].metric("Drawdown proxy", f"{wdd*100:.0f}%")
    if review.hhi > 0.25:
        st.warning("High concentration (HHI > 0.25) — diversify only where it improves "
                   "risk-adjusted return, not for appearance.")

    st.subheader("Stress test (portfolio-weighted, sector-based)")
    st.dataframe(_portfolio_stress(review, fx), width="stretch", hide_index=True)


def _portfolio_stress(review, fx) -> pd.DataFrame:
    from src.reports.templates import _SCENARIO_SECTOR

    tv = review.total_value_sek or 1.0
    rows = []
    for scen, mapping in _SCENARIO_SECTOR.items():
        score = 0.0
        for h in review.holdings:
            w = (h.value_sek or 0) / tv
            sec = h.holding.sector or "Unknown"
            s = mapping.get(sec, mapping.get("default", 0))
            if scen == "USD/SEK swing":
                s = -2 if h.holding.currency == "USD" else (-1 if h.holding.currency != "SEK" else 0)
            score += w * s
        label = ("🟢 Net resilient" if score > 0.3 else "🔴 Net exposed" if score < -0.6
                 else "🟠 Moderate" if score < -0.2 else "🟡 Neutral")
        rows.append({"Scenario": scen, "Weighted sensitivity": round(score, 2), "Read": label})
    return pd.DataFrame(rows)


# ================================= Settings =============================== #
def page_settings() -> None:
    cfg = get_config()
    st.header("Settings")
    ui.disclaimer_banner()

    st.subheader("API status")
    keys = {
        "BORSDATA_API_KEY": "Börsdata (Nordic)", "EODHD_API_KEY": "EODHD (global)",
        "FINNHUB_API_KEY": "Finnhub (global)", "FX_API_KEY": "FX (optional)",
        "ANTHROPIC_API_KEY": "Anthropic (optional memo LLM)",
        "TELEGRAM_BOT_TOKEN": "Telegram (optional)",
    }
    st.dataframe(pd.DataFrame([
        {"Provider": label, "Configured": "✅" if cfg.has_key(env) else "— (mock/none)"}
        for env, label in keys.items()
    ]), width="stretch", hide_index=True)
    st.caption(f"Network allowed: **{cfg.allow_network}** · force_mock: "
               f"**{cfg.get('data.force_mock', False)}** · base ccy: **{cfg.base_currency}**")
    st.caption("This terminal never logs into Avanza, never stores broker credentials, "
               "and never places orders.")

    # -- notifications setup ----------------------------------------------
    st.subheader("Notifications (engine alerts)")
    st.caption("1) Telegram: message **@BotFather** → `/newbot`, copy the token into "
               "`TELEGRAM_BOT_TOKEN`. 2) DM your bot once, then click **Find my chat id** "
               "and put it in `TELEGRAM_CHAT_ID`. 3) **Send test alert** to verify.")
    n1, n2 = st.columns(2)
    if n1.button("Send test alert"):
        from src.engine.notify import send_test

        if send_test():
            st.success("Test alert sent to your configured channel(s).")
        else:
            st.error("Not sent — set TELEGRAM_*/ALERT_EMAIL_* in .env and enable channels "
                     "in config.yaml (engine.alerts.channels), then restart.")
    if n2.button("Find my chat id"):
        from src.alerts.telegram import resolve_chat_ids

        chats = resolve_chat_ids()
        if chats:
            st.dataframe(pd.DataFrame(chats), width="stretch", hide_index=True)
            st.caption("Copy the `id` into TELEGRAM_CHAT_ID in your .env.")
        else:
            st.warning("No chats found. Set TELEGRAM_BOT_TOKEN, DM your bot once, then retry.")

    st.subheader("Portfolio value (for sizing)")
    pv = st.number_input("Approx. portfolio value (SEK)",
                         value=ui.portfolio_value(cfg.portfolio_value_sek), step=10000.0)
    st.session_state["portfolio_value_sek"] = pv

    cc = st.columns(2)
    with cc[0]:
        st.subheader("Scoring weights")
        st.dataframe(pd.DataFrame(
            [{"Factor": k, "Weight": v} for k, v in cfg.scoring_weights().items()]
        ), width="stretch", hide_index=True)
    with cc[1]:
        st.subheader("Risk limits")
        st.dataframe(pd.DataFrame([
            {"Limit": k, "Value": v} for k, v in (cfg.get("risk", {}) or {}).items()
        ]), width="stretch", hide_index=True)
    st.caption("Edit `config.yaml` to change weights/limits, then click "
               "**Reload config & clear cache** below.")

    st.subheader("Watchlist")
    db = get_db()
    wl = db.watchlist_all()
    if wl:
        st.dataframe(pd.DataFrame(wl), width="stretch", hide_index=True)
    w1, w2, w3 = st.columns([2, 1, 1])
    new_t = w1.text_input("Add ticker", "")
    new_e = w2.selectbox("Exchange", ["ST", "US", "EU"], key="wl_ex")
    if w3.button("Add") and new_t.strip():
        db.watchlist_add(new_t.strip(), new_e)
        st.rerun()
    if wl:
        rm = st.selectbox("Remove", [""] + [r["symbol"] for r in wl])
        if rm and st.button("Remove selected"):
            db.watchlist_remove(rm)
            st.rerun()

    st.subheader("Data freshness — recent network calls (audit log)")
    log = read_network_log(30)
    if log:
        st.dataframe(pd.DataFrame(log)[["ts", "provider", "method", "url", "status"]],
                     width="stretch", hide_index=True)
    else:
        st.caption("No outbound network calls logged (running on mock/offline).")

    if st.button("Reload config & clear cache"):
        reload_config()
        st.cache_data.clear()
        st.success("Config reloaded and caches cleared.")
