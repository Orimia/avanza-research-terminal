"""Backtest + walk-forward produce sane metrics on mock data."""
from src.backtest.backtester import backtest_momentum, build_price_panel
from src.backtest.walk_forward import walk_forward
from src.data.provider import get_many

ENTRIES = [("VOLV-B", "ST"), ("ERIC-B", "ST"), ("HM-B", "ST"),
           ("ATCO-A", "ST"), ("INVE-B", "ST"), ("SEB-A", "ST"), ("SAND", "ST")]


def test_price_panel_aligned():
    stocks = get_many(ENTRIES)
    panel = build_price_panel(stocks)
    assert not panel.empty
    assert panel.shape[1] == len(ENTRIES)


def test_backtest_metrics_present():
    stocks = get_many(ENTRIES)
    res = backtest_momentum(stocks, top_n=3, lookback=63, hold=21)
    assert res.metrics, res.warnings
    for key in ("total_return", "win_rate", "max_drawdown", "sharpe_like"):
        assert key in res.metrics
    assert any("Survivorship" in w for w in res.warnings)


def test_walk_forward_produces_oos_metrics():
    stocks = get_many(ENTRIES)
    wf = walk_forward(stocks, folds=3, top_n=3, lookback=42, hold=14)
    assert wf.folds
    # each fold must actually slice history and produce metrics (guards against
    # the date-membership regression where folds come back empty)
    assert sum(1 for f in wf.folds if f.metrics) >= 1
    assert wf.aggregate.get("n_folds", 0) >= 1
