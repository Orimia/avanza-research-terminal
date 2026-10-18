"""Shared UI components and cached data/scoring loaders for the dashboard."""
from __future__ import annotations

import contextlib

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from src.config import get_config
from src.data.fx_client import get_fx_rates
from src.data.provider import get_full_many, get_stock_data
from src.engine.market_hours import is_market_open
from src.models.schemas import Recommendation, ScoreBreakdown, StockData
from src.portfolio.sizing import size_position, suggest_weight
from src.scoring.composite import analyze, build_recommendation, decide_new
from src.scoring.risk import is_high_risk
from src.scoring.technicals import compute_technicals
from src.universe import load_screener_universe

# --- palette (Apple system colors, LIGHT, accessible-contrast variants) -----
# matches .streamlit/config.toml. Text-grade colors chosen for white surfaces.
BG = "#f5f5f7"
PANEL = "#ffffff"
INK = "#1d1d1f"
MUTED = "#6e6e73"
GRID = "rgba(0,0,0,0.08)"
GREEN = "#248a3d"
RED = "#d70015"
AMBER = "#b25000"
BLUE = "#0066cc"

ACTION_COLORS = {
    "BUY": "#248a3d", "WATCH": "#b25000", "HOLD": "#0066cc",
    "TRIM": "#b25000", "SELL": "#d70015", "AVOID": "#6e6e73",
}


# -- banners --------------------------------------------------------------- #
def disclaimer_banner() -> None:
    cfg = get_config()
    st.caption(
        f"Research terminal — no Avanza login, no order execution, no stored "
        f"credentials. Whole shares only · options off · certificates off. {cfg.disclaimer}"
    )


def action_badge(action: str) -> str:
    color = ACTION_COLORS.get(action, "#6b7280")
    return (f"<span style='background:{color}22;color:{color};padding:2px 10px;"
            f"border:1px solid {color}55;border-radius:999px;font-weight:700;"
            f"font-size:0.78rem;letter-spacing:.04em'>{action}</span>")


def confidence_chip(conf: str) -> str:
    c = {"High": GREEN, "Medium": AMBER, "Low": RED}.get(conf, MUTED)
    dot = "●●●" if conf == "High" else "●●○" if conf == "Medium" else "●○○"
    return f"<span style='color:{c};font-weight:600;font-size:0.8rem'>{dot} {conf}</span>"


def tag(text: str, color: str) -> str:
    """Small uppercase type tag (signal feed, tables)."""
    return (f"<span class='tag' style='background:{color}22;color:{color};"
            f"border:0.5px solid {color}44'>{text}</span>")


def panel_header(label: str, right: str = "") -> str:
    r = f"<span class='ph-r'>{right}</span>" if right else ""
    return f"<div class='panel-h'><span>{label}</span>{r}</div>"


def sparkline(closes: list[float], height: int = 44) -> go.Figure:
    """Tiny axis-less line chart (market tape / panel footers)."""
    up = len(closes) >= 2 and closes[-1] >= closes[0]
    c = GREEN if up else RED
    fig = go.Figure(go.Scatter(y=closes, mode="lines",
                               line=dict(color=c, width=1.6),
                               fill="tozeroy", fillcolor=f"rgba({'36,138,61' if up else '215,0,21'},0.10)",
                               hoverinfo="skip"))
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=2, b=0),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      showlegend=False)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    fig.update_yaxes(range=[min(closes) * 0.995, max(closes) * 1.005])
    return fig


def sev_dot(severity: str) -> str:
    """A small monochrome status dot (replaces feed severity emojis)."""
    color = {"critical": RED, "warn": AMBER, "info": BLUE}.get(severity, MUTED)
    return (f"<span style='display:inline-block;width:7px;height:7px;border-radius:50%;"
            f"background:{color};box-shadow:0 0 7px {color}99;margin-right:7px;"
            f"vertical-align:middle'></span>")


def pct_pill(x: float | None, dp: int = 1) -> str:
    if x is None:
        return "<span style='color:#8b98a9'>—</span>"
    c = GREEN if x > 0 else RED if x < 0 else MUTED
    return f"<span style='color:{c};font-weight:600'>{x * 100:+.{dp}f}%</span>"


# -- global styling (Apple-inspired) --------------------------------------- #
def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root {
          --ink:#1d1d1f; --muted:#6e6e73; --tint:#0066cc; --green:#248a3d; --red:#d70015;
          --card:#ffffff; --brd: rgba(0,0,0,0.10);
          --radius: 14px;
        }
        html, body, [class*="css"], .stApp, button, input, textarea, select {
          font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",
                       "Helvetica Neue", Inter, system-ui, sans-serif !important;
          -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
          text-rendering: optimizeLegibility;
          font-feature-settings: "kern" 1, "liga" 1, "calt" 1; letter-spacing: -.003em;
        }
        /* clean, flat light canvas — no gradients */
        .stApp { background: #f5f5f7; }
        /* hide Streamlit chrome */
        #MainMenu, footer, [data-testid="stToolbar"], [data-testid="stDecoration"] { display:none !important; }
        [data-testid="stHeader"] { background: transparent; height: 0; }
        .block-container { padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1560px; }
        div[data-testid="stVerticalBlock"] { gap: 0.65rem; }
        /* tabular, SF-mono numerics — dense terminal sizing */
        [data-testid="stMetricValue"] {
          font-family: "SF Mono", ui-monospace, "JetBrains Mono", monospace !important;
          font-weight: 600 !important; letter-spacing:-.01em; color: var(--ink);
          font-variant-numeric: tabular-nums; font-size: 1.28rem !important;
        }
        [data-testid="stDataFrame"] { font-variant-numeric: tabular-nums; }
        /* white metric cards, hairline border, soft shadow */
        [data-testid="stMetric"] {
          background: var(--card); border: 0.5px solid var(--brd);
          border-radius: 12px; padding: 9px 14px;
          box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 4px 14px rgba(0,0,0,0.04);
          transition: box-shadow .2s ease;
        }
        [data-testid="stMetric"]:hover { box-shadow: 0 2px 4px rgba(0,0,0,0.05), 0 8px 22px rgba(0,0,0,0.07); }
        [data-testid="stMetricLabel"] { color: var(--muted); font-size:0.8rem; font-weight:500; letter-spacing:.01em; }
        /* white bordered containers (panels) */
        [data-testid="stVerticalBlockBorderWrapper"] {
          border-radius: var(--radius) !important; border: 0.5px solid var(--brd) !important;
          background: var(--card);
          box-shadow: 0 1px 2px rgba(0,0,0,0.04), 0 6px 18px rgba(0,0,0,0.04);
        }
        /* sidebar: clean white rail */
        [data-testid="stSidebar"] {
          background: #fbfbfd;
          border-right: 0.5px solid rgba(0,0,0,0.09);
        }
        [data-testid="stSidebar"] { width: 268px !important; }
        [data-testid="stSidebar"] .block-container { padding-top: 1.4rem; }
        /* ---- sidebar nav: real buttons styled as macOS sidebar rows ---- */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 2px; }
        [data-testid="stSidebar"] .stButton > button {
          width:100%; justify-content:flex-start; text-align:left;
          border-radius:8px; border:0 !important; background:transparent;
          color:#3a3a3c; font-weight:500; font-size:0.92rem; letter-spacing:-.01em;
          padding:6px 12px; box-shadow:none !important;
          transition: background .14s ease, color .14s ease;
        }
        [data-testid="stSidebar"] .stButton > button:hover {
          background: rgba(0,0,0,0.05); color:var(--ink);
          transform:none; box-shadow:none !important; border:0 !important;
        }
        [data-testid="stSidebar"] .stButton > button[kind="primary"] {
          background: rgba(0,102,204,0.10); color:var(--tint); font-weight:600;
          box-shadow: none !important;
        }
        [data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {
          background: rgba(0,102,204,0.14); color:var(--tint);
        }
        /* brand lockup + sidebar furniture */
        .brand { display:flex; align-items:center; gap:10px; padding:2px 4px; }
        .brand-mark { width:30px; height:30px; border-radius:8px; flex:none; background:#1d1d1f;
          display:flex; align-items:center; justify-content:center; }
        .brand-title { font-family:"SF Pro Display"; font-weight:650; font-size:1.02rem; color:var(--ink);
          letter-spacing:-.02em; line-height:1.12; }
        .brand-sub { font-size:0.72rem; color:#8e8e93; letter-spacing:.01em; }
        .status-line { font-size:0.78rem; color:#6e6e73; margin:13px 4px 0; display:flex; align-items:center; gap:7px; }
        .status-dot { width:7px; height:7px; border-radius:50%; flex:none; }
        .nav-sep { height:1px; background:rgba(0,0,0,0.08); margin:13px 0; }
        .side-foot { font-size:0.72rem; color:#8e8e93; padding:2px 4px; line-height:1.55; }
        .side-disc { color:#8e8e93; }
        /* professional terminals do not use italics — kill them everywhere,
           including markdown emphasis inside memos and captions */
        em, i { font-style: normal !important; }
        /* typography — SF Pro optical scale */
        h1, h2, h3, h4 {
          font-family: "SF Pro Display", -apple-system, BlinkMacSystemFont, Inter, sans-serif !important;
          color: var(--ink);
        }
        h1 { font-weight:700; letter-spacing:-.032em; font-size:1.5rem; line-height:1.1; margin-bottom:.1rem; }
        h2 { font-weight:640; letter-spacing:-.024em; font-size:1.38rem; line-height:1.2; }
        h3 { font-weight:600; letter-spacing:-.018em; font-size:1.1rem; }
        p, span, label, li, .stMarkdown { color:#1d1d1f; font-size:0.95rem; line-height:1.5; }
        [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {
          color: var(--muted) !important; letter-spacing: 0; line-height: 1.45;
        }
        /* pill buttons */
        .stButton>button {
          border-radius: 980px; border:0.5px solid rgba(0,0,0,0.16);
          background: #ffffff; color: var(--ink); font-weight:600;
          padding: 6px 16px;
          transition: all .18s ease;
        }
        .stButton>button:hover {
          background: rgba(0,102,204,0.06); border-color: var(--tint); color: var(--tint);
        }
        .stButton>button[kind="primary"] { background: var(--tint); border-color: var(--tint); color:#fff; }
        .stButton>button[kind="primary"]:hover { background:#0056ad; color:#fff; }
        /* inputs / selects rounded */
        [data-baseweb="select"]>div, .stTextInput input, .stNumberInput input, [data-baseweb="input"] {
          border-radius: 10px !important;
        }
        /* toggles */
        [data-testid="stWidgetLabel"]+div [aria-checked="true"], [role="switch"][aria-checked="true"] { background: #34c759 !important; }
        /* slider tint */
        [data-testid="stSlider"] [role="slider"] { box-shadow: 0 0 0 6px rgba(0,102,204,0.14); }
        /* dataframe */
        [data-testid="stDataFrame"] { border-radius:12px; overflow:hidden; border:0.5px solid var(--brd); }
        /* tabs */
        [data-baseweb="tab-list"] { gap: 4px; }
        [data-baseweb="tab"] { border-radius: 980px; }
        a { color: var(--tint); text-decoration:none; }
        a:hover { text-decoration:underline; }
        /* thin scrollbar */
        ::-webkit-scrollbar { width: 9px; height: 9px; }
        ::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.18); border-radius: 980px; }
        ::-webkit-scrollbar-track { background: transparent; }
        /* market chips */
        .mkt { display:inline-block; padding:4px 12px; border-radius:980px; font-size:0.78rem;
               font-weight:600; margin-right:8px; border:0.5px solid; }
        .mkt-open { color:var(--green); border-color:rgba(36,138,61,.35); background:rgba(36,138,61,.07); }
        .mkt-closed { color:var(--muted); border-color:rgba(0,0,0,.14); background:rgba(0,0,0,.03); }
        /* subtle fade-in */
        .main .block-container > div { animation: fadein .4s ease; }
        @keyframes fadein { from {opacity:0; transform: translateY(5px);} to {opacity:1; transform:none;} }
        /* ---- terminal panels (AlphaSense-style density) ---- */
        .panel-h { font-size:10.5px; font-weight:650; letter-spacing:.12em; text-transform:uppercase;
                   color:#6e6e73; border-bottom:0.5px solid rgba(0,0,0,0.10);
                   padding-bottom:6px; margin:2px 0 8px; display:flex; justify-content:space-between; }
        .panel-h .ph-r { color:#8e8e93; letter-spacing:0; text-transform:none; font-weight:500; }
        table.term { width:100%; border-collapse:collapse; font-size:12.5px;
                     font-variant-numeric: tabular-nums; }
        table.term th { text-align:right; color:#6e6e73; font-weight:550; font-size:10.5px;
                        letter-spacing:.06em; text-transform:uppercase; padding:3px 8px;
                        border-bottom:0.5px solid rgba(0,0,0,0.12); }
        table.term th:first-child, table.term td:first-child { text-align:left; padding-left:2px; }
        table.term td { text-align:right; padding:4.5px 8px; color:#1d1d1f;
                        border-bottom:0.5px solid rgba(0,0,0,0.05); white-space:nowrap; }
        table.term tr:hover td { background:rgba(0,0,0,0.025); }
        .sym { font-weight:650; color:#111114; letter-spacing:.01em; }
        .sub { color:#6e6e73; font-size:11px; }
        .feed-row { padding:6px 2px; border-bottom:0.5px solid rgba(0,0,0,0.06);
                    font-size:12.5px; line-height:1.45; }
        .feed-row:hover { background:rgba(0,0,0,0.02); }
        .ago { float:right; color:#8e8e93; font-size:10.5px; padding-top:2px; }
        .tag { display:inline-block; border-radius:5px; padding:0.5px 7px; font-size:9.5px;
               font-weight:700; letter-spacing:.07em; text-transform:uppercase; margin-right:7px;
               vertical-align:1px; }
        .tape-item { display:inline-flex; align-items:baseline; gap:7px; margin-right:22px;
                     font-size:12.5px; font-variant-numeric:tabular-nums; }
        .tape-item .tl { color:#6e6e73; font-weight:550; }
        .tape-item .tv { font-weight:650; color:#111114; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def autorefresh(seconds: int, key: str = "auto") -> None:
    """Reload the whole app every ``seconds`` to surface new engine signals.

    Wrapped defensively: ``components.html`` is pending deprecation, so if a
    future Streamlit removes it this degrades to "no auto-refresh" (the engine
    still pushes to Telegram) rather than breaking the page.
    """
    with contextlib.suppress(Exception):  # defensive against API deprecation
        components.html(
            f"<script>setTimeout(function(){{window.parent.location.reload();}}, "
            f"{seconds * 1000});</script>",
            height=0,
        )


def range_bar(tech, price: float | None, currency: str) -> str:
    """52-week range bar with a marker for where the price sits."""
    if not tech or tech.pct_in_range is None or price is None:
        return ""
    pct = max(0.0, min(1.0, tech.pct_in_range)) * 100
    return (
        "<div style='margin:8px 0'>"
        "<div style='display:flex;justify-content:space-between;font-size:0.72rem;color:#86868b'>"
        f"<span>52w low {tech.wk52_low:.0f}</span><span>52w high {tech.wk52_high:.0f}</span></div>"
        "<div style='position:relative;height:6px;border-radius:980px;"
        "background:linear-gradient(90deg,#ff453a55,#ff9f0a55,#30d15855);margin-top:4px'>"
        f"<div style='position:absolute;left:{pct:.1f}%;top:-4px;width:14px;height:14px;"
        "border-radius:50%;background:#1d1d1f;transform:translateX(-50%);"
        "box-shadow:0 0 0 3px rgba(0,102,204,0.45)'></div></div>"
        f"<div style='text-align:center;font-size:0.72rem;color:#a1a1a6;margin-top:3px'>"
        f"{pct:.0f}% of 52-week range · now {price:.0f} {currency}</div></div>"
    )


def market_status_chips() -> str:
    names = {"nordic": "Stockholm", "eu": "EU", "us": "US"}
    out = []
    for region, label in names.items():
        cls = "mkt-open" if is_market_open(region) else "mkt-closed"
        dot = ("<span style='display:inline-block;width:6px;height:6px;border-radius:50%;"
               "background:currentColor;margin-right:6px;vertical-align:middle'></span>")
        out.append(f"<span class='mkt {cls}'>{dot}{label}</span>")
    return "".join(out)


# -- charts ---------------------------------------------------------------- #
def _dark(fig: go.Figure, height: int) -> go.Figure:
    fig.update_layout(
        template="plotly_white", height=height, margin=dict(l=4, r=4, t=10, b=4),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=INK, family="Inter"),
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", y=1.02, x=0),
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def price_chart(data: StockData) -> go.Figure | None:
    if not data.price_history:
        return None
    df = pd.DataFrame([b.model_dump() for b in data.price_history]).tail(220)
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="Price", increasing_line_color=GREEN, decreasing_line_color=RED,
        increasing_fillcolor=GREEN, decreasing_fillcolor=RED))
    for w, color in ((50, BLUE), (200, AMBER)):
        if len(df) >= w:
            df[f"ma{w}"] = df["close"].rolling(w).mean()
            fig.add_trace(go.Scatter(x=df["date"], y=df[f"ma{w}"], name=f"MA{w}",
                                     line=dict(color=color, width=1.3)))
    fig = _dark(fig, 380)
    fig.update_layout(xaxis_rangeslider_visible=False)
    return fig


def score_bars(b: ScoreBreakdown) -> go.Figure:
    items = [(k, v) for k, v in b.as_dict().items() if v is not None]
    labels = [k for k, _ in items]
    vals = [v for _, v in items]
    colors = [GREEN if v >= 65 else AMBER if v >= 45 else RED for v in vals]
    fig = go.Figure(go.Bar(x=vals, y=labels, orientation="h", marker_color=colors,
                           text=[f"{v:.0f}" for v in vals], textposition="auto",
                           marker_line_width=0))
    fig = _dark(fig, 260)
    fig.update_layout(xaxis=dict(range=[0, 100], title="0–100 (higher = better)"),
                      showlegend=False)
    return fig


def exposure_pie(data: dict[str, float], title: str) -> go.Figure:
    palette = [GREEN, BLUE, AMBER, RED, "#7c3aed", "#0891b2", "#db2777", "#64748b"]
    fig = go.Figure(go.Pie(labels=list(data.keys()), values=list(data.values()),
                           hole=0.55, marker=dict(colors=palette),
                           textinfo="label+percent", textfont_size=11))
    fig = _dark(fig, 300)
    fig.update_layout(title=dict(text=title, font=dict(size=14)), showlegend=False,
                      margin=dict(l=4, r=4, t=36, b=4))
    return fig


# -- cached loaders -------------------------------------------------------- #
@st.cache_data(ttl=600, show_spinner=False)
def load_fx() -> dict[str, float]:
    return get_fx_rates()


@st.cache_data(ttl=600, show_spinner=False)
def load_stock(ticker: str, exchange: str) -> StockData:
    return get_stock_data(ticker, exchange)


def _benchmark_ret_3m(stocks: list[StockData]) -> float | None:
    rets = []
    for s in stocks:
        t = compute_technicals(s)
        if t.ret_3m is not None:
            rets.append(t.ret_3m)
    return float(np.median(rets)) if rets else None


def recommend_for(data: StockData, fx: dict[str, float], pv: float,
                  benchmark: float | None, cfg=None) -> Recommendation:
    cfg = cfg or get_config()
    a = analyze(data, fx, benchmark, cfg)
    action, _, _ = decide_new(data, a.breakdown, a.risk_reward, cfg)
    high_risk = is_high_risk(data, a.technicals, cfg)
    weight = suggest_weight(action, a.breakdown, high_risk=high_risk, cfg=cfg)
    sizing = None
    if data.quote:
        turn = data.quote.avg_turnover
        sizing = size_position(data.quote.price, data.currency, fx, pv, weight,
                               avg_turnover_local=turn, high_risk=high_risk, cfg=cfg)
    return build_recommendation(data, fx, sizing=sizing, benchmark_ret_3m=benchmark, cfg=cfg)


@st.cache_data(ttl=900, show_spinner="Screening with full fundamentals + analyst targets…")
def run_screen(region: str, allow_small_cap: bool, pv: float) -> list[dict]:
    """Thesis-correct screen: FULL fundamentals + analyst targets for a curated
    universe (fetched concurrently). Returns serialisable recommendation dicts.
    """
    from src.universe.filters import apply_filters

    from src.scoring.regime import apply_regime, current_regime

    fx = get_fx_rates()
    cfg = get_config()
    cfg, _ = apply_regime(cfg, current_regime(cfg=cfg))   # regime-adaptive BUY bar
    entries = load_screener_universe(region)
    stocks = get_full_many(entries)
    benchmark = _benchmark_ret_3m(stocks)
    passed, results = apply_filters(stocks, fx, allow_small_cap=allow_small_cap)
    recs = [recommend_for(s, fx, pv, benchmark, cfg) for s in passed]
    recs.sort(key=lambda r: r.score.composite, reverse=True)
    excluded = [{"symbol": r.data.symbol, "reasons": r.reasons}
                for r in results if not r.passed]
    return [{"rec": r.model_dump(), "passed": True} for r in recs] + \
           [{"excluded": e} for e in excluded]


def screener_rationale(rec: Recommendation) -> str:
    """One-line 'why chosen' from the thesis factors + analyst view."""
    drivers = [(k, v) for k, v in rec.score.as_dict().items()
               if v is not None and k != "Liquidity"]
    drivers.sort(key=lambda kv: kv[1], reverse=True)
    top = [f"{k.lower()} {v:.0f}" for k, v in drivers[:2] if v >= 55]
    s = ("Strong " + " & ".join(top)) if top else "Balanced/mixed signals"
    val = rec.score.valuation
    if val is not None:
        s += "; " + ("attractively valued" if val >= 60
                     else "rich valuation" if val <= 40 else "fair valuation")
    if rec.analyst and rec.analyst.recommendation:
        n = rec.analyst.n_analysts
        s += f"; sell-side: {rec.analyst.recommendation}" + (f" (n={n})" if n else "")
    return s + "."


def target_block(rec: Recommendation) -> str:
    """HTML for analyst + model price targets with implied upside."""
    rows = []
    au = rec.analyst_upside
    if rec.analyst_target is not None:
        rows.append(f"<b>Analyst</b> {rec.analyst_target:.2f} {rec.currency} "
                    f"{pct_pill(au)}")
    if rec.model_target is not None:
        rows.append(f"<b>Model</b> {rec.model_target:.2f} {rec.currency} "
                    f"{pct_pill(rec.model_upside)}")
    if not rows:
        return "<span style='color:#8b98a9'>no target</span>"
    return " &nbsp;·&nbsp; ".join(rows)


def conviction(rec: Recommendation) -> float:
    """Rank actionable BUYs by composite, nudged by analyst upside + risk/reward."""
    c = rec.score.composite
    if rec.analyst_upside is not None:
        c += max(-10.0, min(15.0, rec.analyst_upside * 100 * 0.35))
    if rec.risk_reward:
        c += max(-4.0, min(8.0, (rec.risk_reward.rr_ratio - 1.5) * 4))
    return c


# one-click thesis lenses — re-rank the same screen by what you care about
THESIS_PRESETS = {
    "Balanced": "balanced",
    "Compounders": "compounders",
    "Deep value": "value",
    "Momentum": "momentum",
    "Income": "income",
}


def preset_rank(rec: Recommendation, preset: str) -> float:
    b = rec.score
    q, g, v, m = (b.quality or 0), (b.growth or 0), (b.valuation or 0), (b.momentum or 0)
    au = (rec.analyst_upside or 0) * 100
    if preset == "compounders":
        return 0.45 * q + 0.30 * g + 0.25 * b.composite
    if preset == "value":
        return 0.45 * v + 0.25 * b.composite + 0.30 * max(0, au)
    if preset == "momentum":
        return 0.50 * m + 0.30 * b.composite + 0.20 * max(0, au)
    if preset == "income":
        return (rec.dividend_yield or 0) * 1000 + 0.25 * b.composite
    return conviction(rec)


def preset_keep(rec: Recommendation, preset: str) -> bool:
    if preset == "income":
        return (rec.dividend_yield or 0) >= 0.015   # only real dividend payers
    return True


def pick_badges(rec: Recommendation) -> str:
    out = []

    def pill(txt, color):
        return (f"<span style='background:{color}1f;color:{color};border:0.5px solid {color}55;"
                f"border-radius:980px;padding:1px 9px;font-size:0.72rem;font-weight:600;"
                f"margin-right:5px'>{txt}</span>")
    if rec.dividend_yield and rec.dividend_yield >= 0.005:
        out.append(pill(f"{rec.dividend_yield * 100:.1f}% div", GREEN))
    if rec.days_to_earnings is not None and 0 <= rec.days_to_earnings <= 14:
        out.append(pill(f"Earnings {rec.days_to_earnings}d", AMBER))
    if rec.sizing and rec.sizing.shares == 0:
        out.append(pill("1 sh &gt; your size", AMBER))
    if rec.technicals and (rec.technicals.volatility or 0) >= 0.5:
        out.append(pill("High vol", RED))
    return "".join(out)


def action_line(rec: Recommendation) -> str:
    """The exact actionable step for a BUY: entry timing · size · target · stop."""
    t, rr, sz = rec.technicals, rec.risk_reward, rec.sizing
    price = rec.price or (rr.entry if rr else None)
    extended = bool(t and (((t.price_vs_ma50 or 0) > 0.12) or ((t.rsi14 or 0) > 73)))
    if extended and t and t.ma50:
        entry = f"<b>Wait for a pullback to ~{t.ma50:.0f}</b> (extended)"
    elif price:
        entry = f"<b>Buy now</b> near {price:.0f}"
    else:
        entry = "<b>Buy</b>"
    parts = [entry]
    if sz and sz.shares > 0:
        parts.append(f"{sz.shares} sh (~{sz.actual_sek:,.0f} kr)")
    # coherent target + stop from the SAME risk/reward (analyst target shown separately)
    if rr:
        parts.append(f"Target {rr.take_profit:.0f} (+{rr.upside_pct * 100:.0f}%)")
        parts.append(f"Stop {rr.stop_loss:.0f} (−{rr.downside_pct * 100:.0f}%)")
    return " · ".join(parts)


def unpack_recs(rows: list[dict]) -> tuple[list[Recommendation], list[dict]]:
    recs, excluded = [], []
    for row in rows:
        if "rec" in row:
            recs.append(Recommendation.model_validate(row["rec"]))
        elif "excluded" in row:
            excluded.append(row["excluded"])
    return recs, excluded


def portfolio_value(default: float) -> float:
    return float(st.session_state.get("portfolio_value_sek", default))


def is_simple() -> bool:
    """Simple mode: plain-language essentials only (sidebar toggle)."""
    return bool(st.session_state.get("simple_mode", False))


# -- crypto: cached loaders + components ----------------------------------- #
@st.cache_data(ttl=900, show_spinner="Pricing your crypto + scoring the market…")
def run_crypto_holdings() -> dict:
    from src.portfolio.crypto_account import analyze_crypto_holdings
    rv = analyze_crypto_holdings()
    return {
        "value_usd": rv.value_usd, "value_sek": rv.value_sek, "cost_usd": rv.cost_usd,
        "unrealized_pct": rv.unrealized_pct, "n_holdings": rv.n_holdings,
        "any_mock": rv.any_mock, "signals": [s.model_dump(mode="json") for s in rv.signals],
    }


@st.cache_data(ttl=900, show_spinner="Scoring the crypto market…")
def run_crypto_discovery(limit: int | None = None) -> list[dict]:
    from src.portfolio.crypto_account import run_crypto_discovery as _run
    return [s.model_dump(mode="json") for s in _run(limit=limit)]


def unpack_crypto(rows: list[dict]):
    from src.models.schemas import CryptoSignal
    return [CryptoSignal.model_validate(r) for r in rows]


def clear_crypto_cache() -> None:
    run_crypto_holdings.clear()
    run_crypto_discovery.clear()


# -- V2: market regime ------------------------------------------------------ #
@st.cache_data(ttl=900, show_spinner=False)
def load_regime() -> dict:
    from src.scoring.regime import apply_regime, current_regime
    cfg = get_config()
    state = current_regime(cfg=cfg)
    _, note = apply_regime(cfg, state)
    return {"label": state.label, "score": state.score, "note": note,
            "components": state.components, "buy_min": state.buy_min_effective}


_REGIME_COLOR = {"risk-on": GREEN, "neutral": AMBER, "risk-off": RED, "unknown": MUTED}


def regime_chip() -> str:
    r = load_regime()
    c = _REGIME_COLOR.get(r["label"], MUTED)
    return (f"<span style='background:{c}1c;color:{c};border:0.5px solid {c}55;"
            f"border-radius:980px;padding:3px 12px;font-size:0.78rem;font-weight:650'>"
            f"Regime · {r['label']}</span> "
            f"<span style='color:#8b98a9;font-size:0.78rem'>{r['note']}</span>")


def crypto_badge(action: str, label: str) -> str:
    color = ACTION_COLORS.get(action, "#6b7280")
    return (f"<span style='background:{color}22;color:{color};padding:2px 11px;"
            f"border:1px solid {color}55;border-radius:999px;font-weight:700;"
            f"font-size:0.78rem;letter-spacing:.02em'>{label}</span>")


_FLAG_PILL = {
    "core": ("Core", GREEN), "dust": ("Dust", MUTED),
    "staked": ("Staked", AMBER), "concentration": ("Concentrated", AMBER),
}


def crypto_flag_pills(flags: list[str], staked_pct: float | None = None) -> str:
    out = []
    for f in flags:
        if f not in _FLAG_PILL:
            continue
        txt, color = _FLAG_PILL[f]
        if f == "staked" and staked_pct:
            txt = f"{staked_pct:.0f}% staked"
        out.append(f"<span style='background:{color}1f;color:{color};border:0.5px solid {color}55;"
                   f"border-radius:980px;padding:1px 9px;font-size:0.72rem;font-weight:600;"
                   f"margin-right:5px'>{txt}</span>")
    return "".join(out)


def tier_chip(tier: int) -> str:
    label = {1: "Tier 1 · blue-chip", 2: "Tier 2 · major L1", 3: "Tier 3 · speculative"}.get(tier, f"Tier {tier}")
    color = {1: GREEN, 2: BLUE, 3: AMBER}.get(tier, MUTED)
    return (f"<span style='color:{color};font-size:0.74rem;font-weight:600'>{label}</span>")
