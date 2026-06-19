"""Mock provider determinism + router fallback (offline)."""
from src.data.mock_provider import MockProvider
from src.data.provider import get_stock_data, region_for_exchange


def test_mock_is_deterministic():
    a = MockProvider().fetch("VOLV-B", "ST")
    b = MockProvider().fetch("VOLV-B", "ST")
    assert a.quote.price == b.quote.price
    assert len(a.price_history) == len(b.price_history)
    assert a.is_mock and a.coverage.is_mock


def test_mock_currency_by_exchange():
    assert MockProvider().fetch("AAPL", "US").currency == "USD"
    assert MockProvider().fetch("ASML", "EU").currency == "EUR"
    assert MockProvider().fetch("VOLV-B", "ST").currency == "SEK"


def test_region_mapping():
    assert region_for_exchange("ST") == "nordic"
    assert region_for_exchange("US") == "us"
    assert region_for_exchange("EU") == "eu"


def test_router_falls_back_to_mock_offline():
    data = get_stock_data("NVDA", "US")
    assert data.is_mock is True
    assert data.quote is not None and data.quote.price > 0
    assert data.fundamentals is not None
    assert len(data.price_history) > 200
