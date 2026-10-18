"""OpenBB provider tests — pure mappers (offline) + chain integration."""
from datetime import date
from types import SimpleNamespace as NS

from src.data.openbb_client import (
    OpenBBClient,
    analyst_from,
    bars_from_results,
    fundamentals_from,
)


def test_bars_mapping_skips_bad_rows():
    rows = [
        NS(date=date(2026, 1, 2), open=10.0, high=11.0, low=9.5, close=10.5, volume=100),
        NS(date=date(2026, 1, 3), open=None, high=None, low=None, close=11.0, volume=None),
        NS(date=date(2026, 1, 4), open=1, high=1, low=1, close=None, volume=1),   # dropped
        NS(date=None, close=5.0),                                                  # dropped
    ]
    bars = bars_from_results(rows)
    assert [b.close for b in bars] == [10.5, 11.0]
    assert bars[1].open == 11.0 and bars[1].volume == 0.0     # None -> safe fills


def test_fundamentals_mapping_and_dividend_percent_units():
    m = NS(pe_ratio=25.0, forward_pe=22.0, gross_margin=0.45, operating_margin=0.30,
           profit_margin=0.25, return_on_equity=1.5, revenue_growth=0.08,
           earnings_growth=0.12, enterprise_to_ebitda=18.0, enterprise_to_revenue=6.0,
           price_to_book=40.0, dividend_yield=4.04)      # PERCENT (verified live)
    f = fundamentals_from(m)
    assert abs(f.dividend_yield - 0.0404) < 1e-9          # always /100 for this source
    assert f.ev_ebitda == 18.0 and f.ev_sales == 6.0 and f.pe == 25.0
    # sub-1% payer must NOT be treated as a fraction (the old 100x bug)
    f2 = fundamentals_from(NS(dividend_yield=0.23, pe_ratio=30.0))
    assert abs(f2.dividend_yield - 0.0023) < 1e-9
    assert fundamentals_from(None) is None
    assert fundamentals_from(NS()) is None                # nothing mapped -> None


def test_analyst_mapping():
    c = NS(target_consensus=316.76, target_high=400.0, target_low=215.0,
           recommendation="Buy", recommendation_mean=2.0, number_of_analysts=42)
    a = analyst_from(c)
    assert a.target_mean == 316.76 and a.n_analysts == 42
    assert a.recommendation == "buy" and a.recommendation_mean == 2.0
    assert analyst_from(NS()) is None


def test_openbb_unavailable_offline_and_in_chain():
    # conftest sets ALLOW_NETWORK=false -> provider must report unavailable
    assert OpenBBClient().available() is False
    from src.data.provider import _REAL
    assert "openbb" in _REAL                              # registered in the chain
    from src.config import get_config
    for region in ("nordic", "eu", "us", "crypto"):
        assert "openbb" in (get_config().get(f"data.providers.{region}") or [])
