"""Dashboard pages: Daily Opportunities, Stock Deep Dive, Backtest."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.config import get_config
from src.dashboard import ui
from src.data.provider import get_stock_data, screen_data
from src.models.schemas import Action
from src.reports.memo_generator import generate_memo
from src.storage.db import get_db
from src.universe import load_universe


def _go_deep_dive(ticker: str, exchange: str) -> None:
    st.session_state["dd_ticker"] = ticker
    st.session_state["dd_exchange"] = exchange
    st.session_state["page"] = "Stock Deep Dive"
    st.rerun()


# ============================ Daily Opportunities ========================= #
def _thesis_caption(cfg) -> None:
    w = cfg.scoring_weights()
    weights = " · ".join(f"{k.title()} {int(v * 100)}%" for k, v in w.items())
    st.caption("**Thesis:** maximize risk-adjusted return · tilt to quality / growth / "
               "momentum · skeptical · no diversification for appearance.")
    st.caption(f"**Composite weights:** {weights}  →  full fundamentals + analyst "
               "targets on a curated, liquid universe.")


def _held_sector_weights() -> dict:
    """Rough current sector weights of the user's portfolio (cached fetches)."""
    from src.data.fx_client import get_fx_rates
    from src.data.provider import get_stock_data
    from src.utils.currency import to_sek
    fx = get_fx_rates()
    holdings = get_db().portfolio_all()
    sec: dict = {}
    total = 0.0
    for h in holdings:
        d = get_stock_data(h.ticker, h.exchange, enrich_news=False)
        val = h.fixed_value_sek if h.fixed_value_sek is not None else (
            to_sek(d.quote.price, h.currency, fx) * h.shares if d.quote else 0)
        s = d.sector or h.sector or "Other"
        sec[s] = sec.get(s, 0.0) + val
        total += val
    return {s: v / total for s, v in sec.items()} if total else {}


def _buy_card(r, rank: int, owned: bool = False, heavy_sectors: set | None = None) -> None:
    with st.container(border=True):
        top = st.columns([3, 1, 1])
        own = " <span style='color:#4aa8ff;font-size:0.75rem'>· you own this</span>" if owned else ""
        top[0].markdown(
            f"<span style='color:#6b7787'>#{rank}</span> &nbsp;"
            f"<span style='font-size:1.2rem;font-weight:800;letter-spacing:.02em'>"
            f"{r.ticker.upper()}</span> <span style='color:#8b98a9'>· {r.exchange}</span>{own}<br>"
            f"<span style='font-size:0.95rem;color:#c4cdd9'>{r.display_name}</span><br>"
            f"{ui.action_badge(r.action.value)} &nbsp; {ui.confidence_chip(r.confidence.value)}",
            unsafe_allow_html=True)
        top[1].metric("Score", f"{r.score.composite:.0f}")
        top[2].metric("R/R", f"{r.risk_reward.rr_ratio:.1f}" if r.risk_reward else "—")
        # the actionable step
        st.markdown(
            f"<div style='background:rgba(48,209,88,0.10);border:0.5px solid rgba(48,209,88,0.4);"
            f"border-radius:12px;padding:9px 13px;margin:5px 0'>{ui.action_line(r)}</div>",
            unsafe_allow_html=True)
        badges = ui.pick_badges(r)
        if badges:
            st.markdown(badges, unsafe_allow_html=True)
        if heavy_sectors and r.sector in heavy_sectors:
            st.caption(f"You're already heavy in {r.sector} — adds concentration, "
                       "not diversification.")
        st.markdown(f"<span style='color:#8b98a9;font-size:0.85rem'>Targets</span> &nbsp;"
                    f"{ui.target_block(r)}", unsafe_allow_html=True)
        st.markdown(f"<span style='color:#c4cdd9'>{ui.screener_rationale(r)}</span>  \n"
                    f"<span style='color:#8b98a9;font-size:0.82rem'>Risk · {r.biggest_risk}</span>",
                    unsafe_allow_html=True)
        row = st.columns([3, 1, 1])
        if row[1].button("Deep dive", key=f"dd_{r.symbol}"):
            _go_deep_dive(r.ticker, r.exchange)
        if row[2].button("Watch", key=f"wl_{r.symbol}"):
            get_db().watchlist_add(r.ticker, r.exchange)
            st.toast(f"Added {r.ticker.upper()} to watchlist", icon="⭐")


def page_opportunities() -> None:
    cfg = get_config()
    st.header("Stock Screener")
    ui.disclaimer_banner()
    _thesis_caption(cfg)

    c1, c2, c3 = st.columns([1.3, 3, 0.8])
    region = c1.selectbox("Region", ["best", "nordic", "eu", "us"],
                          format_func=lambda r: "🌍 Best ideas (all)" if r == "best" else r.title())
    preset_label = c2.radio("Lens", list(ui.THESIS_PRESETS), horizontal=True,
                            label_visibility="collapsed")
    preset = ui.THESIS_PRESETS[preset_label]
    if c3.button("Refresh", help="Pull fresh live prices & re-score now"):
        ui.run_screen.clear()
        st.cache_data.clear()
        st.rerun()
    cc1, cc2 = st.columns([1, 3])
    small_cap = cc1.toggle("Small caps", value=False)
    min_score = cc2.slider("Min composite score", 0, 100, 50)

    pv = ui.portfolio_value(cfg.portfolio_value_sek)
    if region == "best":
        rows = []
        for rg in ("nordic", "eu", "us"):
            rows += ui.run_screen(rg, small_cap, pv)
    else:
        rows = ui.run_screen(region, small_cap, pv)
    recs, excluded = ui.unpack_recs(rows)
    seen: set = set()
    recs = [r for r in recs if not (r.symbol in seen or seen.add(r.symbol))]
    held = {h.symbol for h in get_db().portfolio_all()}
    st.caption(f"{len(recs)} names · **{preset_label}** lens · live prices + analyst targets "
               "(cached ≤15 min — Refresh for live). Names you own are hidden from BUY ideas.")

    sectors = sorted({r.sector for r in recs if r.sector})
    ccys = sorted({r.currency for r in recs})
    f1, f2, f3 = st.columns([2, 2, 1])
    pick_sectors = f1.multiselect("Sectors", sectors, default=sectors)
    pick_ccys = f2.multiselect("Currencies", ccys, default=ccys)
    hide_owned = f3.toggle("Hide owned", value=True)

    def keep(r):
        return (r.score.composite >= min_score and ui.preset_keep(r, preset) and
                (not pick_sectors or r.sector in pick_sectors) and
                r.currency in pick_ccys and
                not (hide_owned and r.symbol in held))

    rank = lambda r: ui.preset_rank(r, preset)  # noqa: E731
    buys = sorted([r for r in recs if r.action == Action.BUY and keep(r)], key=rank, reverse=True)
    watch = sorted([r for r in recs if r.action == Action.WATCH and keep(r)], key=rank, reverse=True)
    avoid = [r for r in recs if r.action == Action.AVOID]

    daily_cap = pv * float(cfg.get("risk.max_daily_new_buying_pct", 0.10))
    planned = sum(r.sizing.actual_sek for r in buys[:8] if r.sizing)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Actionable BUYs", len(buys))
    m2.metric("On watch", len(watch))
    m3.metric("Top-8 cost (SEK)", f"{planned:,.0f}")
    m4.metric("Daily budget (SEK)", f"{daily_cap:,.0f}",
              delta=f"{daily_cap - planned:,.0f} left",
              delta_color="normal" if planned <= daily_cap else "inverse")

    st.subheader(f"Top BUY ideas — {preset_label}")
    if not buys:
        st.info("No names clear the BUY bar with current filters/lens. Lower the min score, "
                "widen filters, switch lens, or hit Refresh.")
    heavy = {s for s, w in (_held_sector_weights().items() if held else []) if w >= 0.18}
    for i, r in enumerate(buys[:8], start=1):
        _buy_card(r, rank=i, owned=r.symbol in held, heavy_sectors=heavy)

    st.subheader("Watchlist — good names, wait for a better entry")
    _table(watch)
    _csv_download(buys + watch, region, preset_label)
    with st.expander(f"⚫ Avoid ({len(avoid)}) & filtered-out ({len(excluded)})"):
        _table(avoid)
        if excluded:
            st.markdown("**Excluded by liquidity / market-cap / penny filters:**")
            st.dataframe(pd.DataFrame([
                {"Symbol": e["symbol"], "Reasons": "; ".join(e["reasons"])} for e in excluded
            ]), width="stretch", hide_index=True)


def _table(recs: list) -> None:
    if not recs:
        st.caption("None.")
        return
    df = pd.DataFrame([{
        "Ticker": r.ticker.upper(), "Name": r.display_name, "Action": r.action.value,
        "Score": round(r.score.composite), "Conf": r.confidence.value,
        "Analyst tgt": round(r.analyst_target, 2) if r.analyst_target else None,
        "Analyst ▲%": round(r.analyst_upside * 100, 1) if r.analyst_upside is not None else None,
        "Model ▲%": round(r.model_upside * 100, 1) if r.model_upside is not None else None,
        "Div %": round(r.dividend_yield * 100, 1) if r.dividend_yield else None,
        "Qual": r.score.quality, "Grw": r.score.growth, "Mom": r.score.momentum,
        "Val": r.score.valuation, "Shares": r.sizing.shares if r.sizing else None,
        "Ccy": r.currency, "Sector": r.sector,
    } for r in recs])
    st.dataframe(df, width="stretch", hide_index=True)


def _csv_download(recs: list, region: str, preset: str) -> None:
    if not recs:
        return
    import re
    df = pd.DataFrame([{
        "ticker": r.ticker.upper(), "name": r.display_name, "action": r.action.value,
        "score": round(r.score.composite), "confidence": r.confidence.value,
        "price": round(r.price, 2) if r.price else None, "ccy": r.currency,
        "analyst_target": r.analyst_target,
        "analyst_upside_pct": round(r.analyst_upside * 100, 1) if r.analyst_upside is not None else None,
        "model_target": r.model_target,
        "model_upside_pct": round(r.model_upside * 100, 1) if r.model_upside is not None else None,
        "stop": r.risk_reward.stop_loss if r.risk_reward else None,
        "rr": r.risk_reward.rr_ratio if r.risk_reward else None,
        "shares": r.sizing.shares if r.sizing else None,
        "sek": round(r.sizing.actual_sek) if r.sizing else None,
        "Q": r.score.quality, "G": r.score.growth, "V": r.score.valuation, "M": r.score.momentum,
        "div_yield_pct": round(r.dividend_yield * 100, 2) if r.dividend_yield else None,
        "days_to_earnings": r.days_to_earnings, "sector": r.sector,
    } for r in recs])
    slug = re.sub(r"[^a-z0-9]+", "-", preset.lower()).strip("-")
    st.download_button("Export CSV", df.to_csv(index=False).encode(),
                       file_name=f"screen_{region}_{slug}.csv", mime="text/csv")


# ============================== Stock Deep Dive =========================== #
def page_deep_dive() -> None:
    cfg = get_config()
    st.header("Stock Deep Dive")
    ui.disclaimer_banner()

    c1, c2, c3 = st.columns([2, 1, 1])
    ticker = c1.text_input("Ticker", st.session_state.get("dd_ticker", "VOLV-B"))
    exchanges = ["ST", "US", "EU"]
    want_ex = st.session_state.get("dd_exchange", "ST")
    exchange = c2.selectbox("Exchange", exchanges,
                            index=exchanges.index(want_ex) if want_ex in exchanges else 0)
    force = c3.toggle("Force refresh", value=False)

    if not ticker:
        st.info("Enter a ticker.")
        return

    if force:
        data = get_stock_data(ticker.strip(), exchange, force_refresh=True)
        ui.load_stock.clear()
    else:
        data = ui.load_stock(ticker.strip(), exchange)

    fx = ui.load_fx()
    pv = ui.portfolio_value(cfg.portfolio_value_sek)
    rec = ui.recommend_for(data, fx, pv, None)

    if data.is_mock:
        st.warning("⚠️ MOCK DATA for this symbol (no key/network). Synthetic — demo only.")

    h = st.columns([2, 1, 1, 1])
    h[0].markdown(f"### {data.name or ticker} ({rec.symbol})  \n"
                  f"{ui.action_badge(rec.action.value)} &nbsp; "
                  f"{ui.confidence_chip(rec.confidence.value)}", unsafe_allow_html=True)
    h[1].metric("Composite", f"{rec.score.composite:.0f}")
    if data.quote:
        h[2].metric("Price", f"{data.quote.price:.2f} {data.currency}")
    if rec.sizing:
        h[3].metric("Suggested", f"{rec.sizing.shares} sh")

    # quick actions
    a1, _ = st.columns([1, 5])
    if a1.button("Add to watchlist"):
        get_db().watchlist_add(ticker.strip(), exchange)
        st.toast(f"Added {rec.symbol} to watchlist", icon="⭐")

    # 52-week range context
    if rec.technicals and data.quote:
        st.markdown(ui.range_bar(rec.technicals, data.quote.price, data.currency),
                    unsafe_allow_html=True)

    left, right = st.columns([3, 2])
    fig = ui.price_chart(data)
    if fig:
        left.plotly_chart(fig, width="stretch")
    right.plotly_chart(ui.score_bars(rec.score), width="stretch")

    # latest news with clickable, cited links
    if data.news:
        with st.expander(f"📰 Latest news ({len(data.news)})", expanded=False):
            for n in data.news[:8]:
                ts = n.timestamp.strftime("%Y-%m-%d %H:%M")
                st.markdown(f"- [{n.title}]({n.url}) — *{n.source}, {ts}*")

    # opportunity cost vs loaded portfolio (if any)
    opp = {}
    holdings = st.session_state.get("holdings")
    if holdings:
        from src.portfolio.opportunity_cost import analyze_portfolio, opportunity_cost

        review = analyze_portfolio(holdings, fx)
        opp = opportunity_cost(rec.score, review.weakest())

    memo = generate_memo(data, rec, opp_cost=opp)
    st.markdown("---")
    st.markdown(memo)

    b1, b2 = st.columns([1, 4])
    if b1.button("Save memo"):
        mid = get_db().memo_save(rec.symbol, rec.action.value, rec.confidence.value,
                                 rec.score.composite, memo)
        st.success(f"Saved memo #{mid}")
    hist = get_db().memo_history(rec.symbol)
    if hist:
        with st.expander("Memo history"):
            st.dataframe(pd.DataFrame(hist), width="stretch", hide_index=True)
    with st.expander("Raw data (sources & freshness)"):
        st.json({"sources": data.sources, "is_mock": data.is_mock,
                 "coverage": data.coverage.model_dump(),
                 "quote": data.quote.model_dump() if data.quote else None,
                 "fundamentals": data.fundamentals.model_dump() if data.fundamentals else None})


# ================================ Backtest ================================ #
def page_backtest() -> None:
    st.header("Backtest & Walk-Forward")
    ui.disclaimer_banner()
    st.caption("Technical/momentum signal only · survivorship-biased universe · "
               "sanity check, **not** a track record.")

    c = st.columns(5)
    region = c[0].selectbox("Region", ["nordic", "us", "eu"], format_func=str.title)
    top_n = c[1].slider("Top N", 3, 15, 5)
    lookback = c[2].slider("Lookback (d)", 21, 126, 63, step=7)
    hold = c[3].slider("Hold (d)", 5, 63, 21, step=1)
    folds = c[4].slider("WF folds", 2, 6, 4)

    if not st.button("Run backtest"):
        return

    from src.backtest.backtester import backtest_momentum
    from src.backtest.walk_forward import walk_forward

    with st.spinner("Fetching history & backtesting…"):
        stocks = screen_data(load_universe(region))
        res = backtest_momentum(stocks, top_n=top_n, lookback=lookback, hold=hold)
        wf = walk_forward(stocks, folds=folds, top_n=top_n, lookback=lookback, hold=hold)

    for w in res.warnings:
        st.warning(w)
    if not res.metrics:
        return

    m = res.metrics
    g = st.columns(4)
    g[0].metric("Total return", f"{m['total_return']*100:.1f}%")
    g[1].metric("CAGR", f"{m['cagr']*100:.1f}%")
    g[2].metric("Sharpe-like", f"{m['sharpe_like']:.2f}")
    g[3].metric("Max drawdown", f"{m['max_drawdown']*100:.1f}%")
    g2 = st.columns(4)
    g2[0].metric("Win rate (periods)", f"{m['win_rate']*100:.0f}%")
    g2[1].metric("Hit rate (picks)", f"{m['hit_rate']*100:.0f}%")
    g2[2].metric("Avg period return", f"{m['avg_period_return']*100:.2f}%")
    g2[3].metric("Rebalances", res.n_rebalances)

    if res.equity_curve:
        df = pd.DataFrame(res.equity_curve, columns=["date", "equity"])
        fig = go.Figure(go.Scatter(x=df["date"], y=df["equity"], mode="lines"))
        fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0),
                          yaxis_title="Equity (×)")
        st.plotly_chart(fig, width="stretch")

    st.subheader("Walk-forward (out-of-sample folds)")
    for w in wf.warnings:
        st.info(w)
    if wf.aggregate:
        st.json(wf.aggregate)
        st.dataframe(pd.DataFrame([
            {"fold": i + 1, **f.metrics} for i, f in enumerate(wf.folds) if f.metrics
        ]), width="stretch", hide_index=True)
