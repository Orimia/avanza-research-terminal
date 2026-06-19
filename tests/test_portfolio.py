"""Portfolio CSV import + portfolio analytics."""
import pytest

from src.config import PROJECT_ROOT, get_config
from src.models.schemas import Action, Holding, HoldingAnalysis
from src.portfolio.import_avanza_csv import load_holdings_csv, parse_holdings
from src.portfolio.opportunity_cost import _trade_plan, analyze_portfolio

SAMPLE = PROJECT_ROOT / "examples" / "sample_portfolio.csv"


def _ha(kind, shares, price_sek, value_sek, action, **kw):
    h = Holding(ticker="X", exchange="US", shares=shares, average_cost=50,
                currency="USD", kind=kind, **kw)
    return HoldingAnalysis(holding=h, price_sek=price_sek, value_sek=value_sek, action=action)


def test_trade_plan_trim_whole_shares():
    cfg = get_config()  # max_new_position_pct = 0.05 -> target 5,000 of 100,000
    ha = _ha("stock", 10, 1000.0, 10000.0, Action.TRIM)
    _trade_plan(ha, 100000.0, cfg)            # excess 5,000 / 1,000 = 5 shares
    assert ha.trade_shares == -5 and "TRIM 5 sh" in ha.trade_note


def test_trade_plan_sell_all_shares():
    ha = _ha("stock", 4, 1000.0, 4000.0, Action.SELL)
    _trade_plan(ha, 100000.0, get_config())
    assert ha.trade_shares == -4 and "SELL all" in ha.trade_note


def test_trade_plan_fund_is_sek_not_shares():
    ha = _ha("fund", 0, 2000.0, 10000.0, Action.TRIM, fixed_value_sek=10000.0)
    _trade_plan(ha, 100000.0, get_config())
    assert ha.trade_shares == 0 and "SEK" in ha.trade_note and ha.trade_sek < 0


def test_parse_sample():
    holdings = load_holdings_csv(SAMPLE)
    assert len(holdings) >= 5
    h = holdings[0]
    assert h.ticker and h.exchange and h.shares > 0
    assert h.current_price is None  # blank optional column


def test_parse_rejects_missing_columns():
    with pytest.raises(ValueError):
        parse_holdings("foo,bar\n1,2\n")


def test_analyze_portfolio_weights_sum_100():
    holdings = load_holdings_csv(SAMPLE)
    fx = {"SEKSEK": 1.0, "USDSEK": 10.5, "EURSEK": 11.3}
    review = analyze_portfolio(holdings, fx)
    assert review.total_value_sek > 0
    total_weight = sum(h.weight_pct for h in review.holdings)
    assert abs(total_weight - 100.0) < 1.0
    assert review.weakest() is not None
    # currency exposure should roughly sum to 100%
    assert abs(sum(review.currency_exposure.values()) - 100.0) < 1.0
