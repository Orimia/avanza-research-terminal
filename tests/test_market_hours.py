"""Market-hours gating (timezone + weekday aware)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from src.engine.market_hours import any_market_open, is_market_open

NY = ZoneInfo("America/New_York")
STO = ZoneInfo("Europe/Stockholm")


def test_us_session():
    # Monday 2025-01-06 10:00 ET -> open; 08:00 -> pre-open
    assert is_market_open("us", datetime(2025, 1, 6, 10, 0, tzinfo=NY)) is True
    assert is_market_open("us", datetime(2025, 1, 6, 8, 0, tzinfo=NY)) is False


def test_weekend_closed():
    # Saturday 2025-01-04
    assert is_market_open("us", datetime(2025, 1, 4, 12, 0, tzinfo=NY)) is False
    assert is_market_open("nordic", datetime(2025, 1, 4, 12, 0, tzinfo=STO)) is False


def test_nordic_session():
    assert is_market_open("nordic", datetime(2025, 1, 6, 10, 0, tzinfo=STO)) is True
    assert is_market_open("nordic", datetime(2025, 1, 6, 18, 0, tzinfo=STO)) is False


def test_any_market_open():
    # During US session, at least one market open
    assert any_market_open(["nordic", "eu", "us"], datetime(2025, 1, 6, 10, 0, tzinfo=NY)) is True
    # Deep night Stockholm on a weekday: all closed
    assert any_market_open(["nordic", "eu", "us"], datetime(2025, 1, 6, 3, 0, tzinfo=STO)) is False
