"""Intelligence page: regime, portfolio X-ray, Monte Carlo, discipline,
paper track record, and signal self-calibration — the V2 adaptive layer."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.dashboard import ui
from src.data.fx_client import get_fx_rates
from src.data.provider import get_stock_data
from src.storage.db import get_db


# -- cached loaders --------------------------------------------------------- #
@st.cache_data(ttl=600, show_spinner="Analyzing your portfolio…")
def _review_payload():
    holdings = get_db().portfolio_all()
    if not holdings:
        return None
    from src.portfolio.opportunity_cost import analyze_portfolio

    return analyze_portfolio(holdings, get_fx_rates())


@st.cache_data(ttl=900, show_spinner="Running the correlation X-ray + Monte Carlo…")
def _xray_payload():
    holdings = [h for h in get_db().portfolio_all() if h.whole_share_instrument]
    if len(holdings) < 2:
        return None, None
    from src.portfolio.intelligence import build_xray, monte_carlo
    from src.utils.currency import to_sek

    fx = get_fx_rates()
    datas, values = {}, {}
    for h in holdings:
        d = get_stock_data(h.ticker, h.exchange, enrich_news=False)
        datas[h.ticker] = d
        px = d.quote.price if d.quote else None
        values[h.ticker] = to_sek(px, h.currency, fx) * h.shares if px else 0.0
    try:
        bench = get_stock_data("^GSPC", "US", enrich_news=False)
    except Exception:
        bench = None
    x = build_xray(holdings, values, datas, benchmark=bench)
    mc = monte_carlo(x, datas)
    return x, mc


# -- sections --------------------------------------------------------------- #
def _regime_section() -> None:
    st.subheader("Market regime")
    r = ui.load_regime()
    c1, c2 = st.columns([3, 1])
    c1.markdown(ui.regime_chip(), unsafe_allow_html=True)
    if c2.button("Refresh regime"):
        ui.load_regime.clear()
        from src.scoring.regime import current_regime

        current_regime(force_refresh=True)
        st.rerun()
    if r["components"]:
        df = pd.DataFrame([
            {"Benchmark": k, "Trend": v["trend"], "Momentum": v["momentum"],
             "Vol": v["vol"], "3m %": round((v["ret_3m"] or 0) * 100, 1),
             "vs 200d %": round((v["vs_ma200"] or 0) * 100, 1),
             "Vol ratio": v["vol_ratio"]}
            for k, v in r["components"].items()
        ])
        st.dataframe(df, width="stretch", hide_index=True)
        st.caption("Components are −1 / 0 / +1 per benchmark. The label adapts the "
                   "screener and engine BUY bar — harder in risk-off, easier in risk-on. "
                   "Always shown, never silent.")
    else:
        st.info("No live benchmark data (offline or market source unavailable) — "
                "thresholds unchanged.")


def _xray_section() -> None:
    st.subheader("Portfolio X-ray — how many bets do you really own?")
    x, mc = _xray_payload()
    if x is None:
        st.info("Add at least two priced holdings to run the X-ray.")
        return
    if x.corr is None:
        st.info(x.note or "Not enough overlapping history yet.")
        return
    m = st.columns(4)
    m[0].metric("Holdings analyzed", len(x.tickers))
    m[1].metric("Effective bets", f"{x.effective_bets:.1f}" if x.effective_bets else "—",
                help="How many independent positions this portfolio behaves like "
                     "(correlation-adjusted). 10 names moving together ≈ 2-3 bets.")
    m[2].metric("Avg correlation", f"{x.avg_corr:.2f}" if x.avg_corr is not None else "—")
    m[3].metric("Beta vs S&P 500", f"{x.beta:.2f}" if x.beta is not None else "—")

    for grp in x.clusters:
        st.warning(f"Same-bet cluster: {', '.join(grp)} move together (corr ≥ 0.70) — "
                   "size them as ONE position, not several.")
    if x.excluded:
        st.caption(f"Excluded (no usable real history): {', '.join(x.excluded)}")

    fig = go.Figure(go.Heatmap(z=x.corr.values, x=x.corr.columns, y=x.corr.index,
                               zmin=-1, zmax=1, colorscale="RdBu", reversescale=True))
    ui._dark(fig, 360)
    st.plotly_chart(fig, width="stretch")

    if mc:
        st.markdown("#### One-year Monte Carlo (bootstrap of your own history)")
        k = st.columns(4)
        k[0].metric("P5 (bad year)", f"{(mc.p5 - 1) * 100:+.0f}%")
        k[1].metric("Median", f"{(mc.p50 - 1) * 100:+.0f}%")
        k[2].metric("P95 (great year)", f"{(mc.p95 - 1) * 100:+.0f}%")
        k[3].metric("P(down year)", f"{mc.prob_loss * 100:.0f}%")
        st.caption(f"{mc.n_sims:,} simulations resampling your holdings' actual joint "
                   f"daily returns (correlations preserved) · median max drawdown along "
                   f"the path {mc.mdd_p50 * 100:.0f}%. History-based, not a forecast — "
                   "regimes change.")


def _discipline_section(review) -> None:
    st.subheader("Discipline — your rules, enforced by a second opinion")
    from src.portfolio.discipline import check_holdings, profile_summary

    st.caption(f"Your profile: {profile_summary()}")
    if review is None:
        st.info("Load your portfolio to run the discipline check.")
        return
    flags = check_holdings(review)
    if not flags:
        st.success("No rule violations in the current proposed actions.")
        return
    for f in flags:
        line = f"{f.symbol} · {f.rule}: {f.message}"
        st.warning(line) if f.severity == "warn" else st.info(line)


def _track_record_section() -> None:
    st.subheader("Track record — is the engine actually any good?")
    from src.backtest.efficacy import signal_efficacy
    from src.portfolio.paper import track_record

    tr = track_record(get_fx_rates())
    m = st.columns(4)
    m[0].metric("Paper positions", f"{tr.n_open} open / {tr.n_closed} closed")
    m[1].metric("Realized P&L", f"{tr.realized_sek:+,.0f} SEK")
    m[2].metric("Unrealized P&L", f"{tr.unrealized_sek:+,.0f} SEK")
    m[3].metric("Hit rate (closed)", f"{tr.hit_rate * 100:.0f}%" if tr.hit_rate is not None else "—")
    st.caption("Every engine signal is filled as a PAPER trade (virtual, sized like a real "
               "suggestion). This is the terminal's accountable, live track record — "
               "no real orders, ever.")
    if tr.open_rows:
        st.dataframe(pd.DataFrame([{
            "Opened": r["opened_at"][:10], "Symbol": r["symbol"], "Qty": r["qty"],
            "Entry": r["entry_price"], "Entry SEK": round(r["entry_sek"]),
            "Mark SEK": r.get("mark_sek"), "Unreal SEK": r.get("unreal_sek"),
            "Source": r["source"],
        } for r in tr.open_rows]), width="stretch", hide_index=True)
    if tr.closed_rows:
        with st.expander(f"Closed paper trades ({tr.n_closed})"):
            st.dataframe(pd.DataFrame([{
                "Opened": r["opened_at"][:10], "Closed": (r["closed_at"] or "")[:10],
                "Symbol": r["symbol"], "P&L SEK": round(r["pnl_sek"] or 0),
                "Note": r["note"],
            } for r in tr.closed_rows]), width="stretch", hide_index=True)

    # cumulative P&L curve of the engine's own calls (the honest scoreboard)
    closed = sorted(tr.closed_rows, key=lambda r: r.get("closed_at") or "")
    if len(closed) >= 2:
        import plotly.graph_objects as go
        xs, ys, cum = [], [], 0.0
        for r in closed:
            cum += float(r["pnl_sek"] or 0)
            xs.append((r.get("closed_at") or "")[:10])
            ys.append(round(cum))
        fig = go.Figure(go.Scatter(x=xs, y=ys, mode="lines+markers",
                                   line=dict(color=ui.GREEN if cum >= 0 else ui.RED, width=2)))
        fig.add_hline(y=0, line_color="rgba(0,0,0,0.25)", line_width=1)
        ui._dark(fig, 240)
        fig.update_layout(yaxis_title="Cumulative paper P&L (kr)")
        st.plotly_chart(fig, width="stretch")
        st.caption("Realized paper-trade P&L over time — the engine's calls, marked to "
                   "reality. An index comparison unlocks once there are 5+ closed trades "
                   "(before that it would be noise dressed as insight).")
    elif tr.n_closed or tr.n_open:
        st.caption("The P&L curve appears after two or more closed paper trades.")

    st.markdown("#### Signal self-calibration")
    rep = signal_efficacy()
    if rep.rows:
        st.dataframe(pd.DataFrame([{
            "Signal": r.signal_type, "N": r.n, "Median fwd %": r.median_fwd_pct,
            "Hit rate": f"{r.hit_rate * 100:.0f}%" if r.hit_rate is not None else "—",
        } for r in rep.rows]), width="stretch", hide_index=True)
    st.caption(rep.note)


def page_intel() -> None:
    st.header("Intelligence")
    ui.disclaimer_banner()
    st.caption("The adaptive layer: what kind of market this is, what your portfolio "
               "really is, whether proposed actions break your own rules, and whether "
               "the engine's calls have been any good. All measured, nothing promised.")
    _regime_section()
    st.markdown("---")
    review = _review_payload()
    _xray_section()
    st.markdown("---")
    _discipline_section(review)
    st.markdown("---")
    _track_record_section()
