"""Avanza Research Terminal — Streamlit entry point.

Run with:  streamlit run src/dashboard/app.py

Research only. This app NEVER logs into Avanza, NEVER places orders, and NEVER
stores broker credentials. It produces a research dashboard and decision memos
so you can place whole-share orders manually yourself.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make `src.*` importable when launched directly via `streamlit run`.
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st  # noqa: E402

from src.config import get_config  # noqa: E402
from src.dashboard.ui import inject_css  # noqa: E402
from src.dashboard.views_alerts import page_alerts  # noqa: E402
from src.dashboard.views_crypto import page_crypto  # noqa: E402
from src.dashboard.views_overview import page_overview  # noqa: E402
from src.dashboard.views_portfolio import page_portfolio, page_risk, page_settings  # noqa: E402
from src.dashboard.views_screen import (  # noqa: E402
    page_backtest,
    page_deep_dive,
    page_opportunities,
)
from src.utils.logging import setup_logging  # noqa: E402

PAGES = {
    "Overview": page_overview,
    "Alerts & Engine": page_alerts,
    "Daily Opportunities": page_opportunities,
    "Crypto Signals": page_crypto,
    "Portfolio Review": page_portfolio,
    "Stock Deep Dive": page_deep_dive,
    "Risk Dashboard": page_risk,
    "Backtest": page_backtest,
    "Settings": page_settings,
}
def _status() -> tuple[str, str]:
    """(dot colour, label) for the data-source status line."""
    cfg = get_config()
    if cfg.get("data.force_mock", False) or not cfg.allow_network:
        return "#ff9f0a", "Mock mode (offline)"
    if any(cfg.has_key(k) for k in ("BORSDATA_API_KEY", "EODHD_API_KEY", "FINNHUB_API_KEY")):
        return "#30d158", "Live data — API keys"
    try:
        from src.data.yahoo_client import YahooClient

        if YahooClient().available():
            return "#30d158", "Live data — Yahoo Finance"
    except Exception:
        pass
    return "#ff9f0a", "Mock data (no source)"


def main() -> None:
    st.set_page_config(page_title="Avanza Research Terminal", page_icon="📈",
                       layout="wide", initial_sidebar_state="expanded")
    setup_logging()
    inject_css()

    pages = list(PAGES)
    selected = st.session_state.get("page", pages[0])
    if selected not in pages:
        selected = pages[0]

    # Real buttons (not a radio) styled as macOS sidebar rows; the active page
    # is the primary-styled button. session_state['page'] also drives programmatic
    # navigation (e.g. "open deep dive") elsewhere in the app.
    with st.sidebar:
        st.markdown(
            "<div class='brand'><div class='brand-mark'></div>"
            "<div><div class='brand-title'>Research Terminal</div>"
            "<div class='brand-sub'>Screen · Score · Decide</div></div></div>",
            unsafe_allow_html=True)
        color, label = _status()
        st.markdown(
            f"<div class='status-line'><span class='status-dot' "
            f"style='color:{color};background:{color}'></span>{label}</div>",
            unsafe_allow_html=True)
        st.markdown("<div class='nav-sep'></div>", unsafe_allow_html=True)
        for p in pages:
            if st.button(p, key=f"nav_{p}", use_container_width=True,
                         type="primary" if p == selected else "secondary"):
                st.session_state["page"] = p
                st.rerun()
        st.markdown("<div class='nav-sep'></div>", unsafe_allow_html=True)
        st.markdown(
            "<div class='side-foot'>No broker login · no orders · whole shares only<br>"
            f"<span class='side-disc'>{get_config().disclaimer}</span></div>",
            unsafe_allow_html=True)

    PAGES[selected]()


main()
