"""Smoke-test every dashboard page through Streamlit AppTest (offline/mock)."""
from streamlit.testing.v1 import AppTest

from src.config import PROJECT_ROOT
from src.portfolio.import_avanza_csv import load_holdings_csv

APP = str(PROJECT_ROOT / "src" / "dashboard" / "app.py")
PAGES = [
    "Overview", "Alerts & Engine", "Daily Opportunities", "Portfolio Review",
    "Stock Deep Dive", "Risk Dashboard", "Backtest", "Settings",
]


def test_all_pages_render_without_exception():
    holdings = load_holdings_csv(PROJECT_ROOT / "examples" / "sample_portfolio.csv")
    for page in PAGES:
        at = AppTest.from_file(APP, default_timeout=180)
        at.session_state["page"] = page
        if page in ("Overview", "Portfolio Review", "Risk Dashboard"):
            at.session_state["holdings"] = holdings
        at.run()
        assert not at.exception, f"{page}: {at.exception}"
