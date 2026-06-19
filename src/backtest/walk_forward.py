"""Walk-forward validation: run the backtest over sequential out-of-sample folds."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from src.backtest.backtester import BacktestResult, backtest_momentum, build_price_panel
from src.models.schemas import StockData


@dataclass
class WalkForwardResult:
    folds: list[BacktestResult] = field(default_factory=list)
    aggregate: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def walk_forward(stocks: list[StockData], *, folds: int = 4, top_n: int = 5,
                 lookback: int = 63, hold: int = 21) -> WalkForwardResult:
    out = WalkForwardResult()
    panel = build_price_panel(stocks)
    if panel.empty or panel.shape[0] < (lookback + hold) * folds:
        out.warnings.append("Not enough history for the requested number of folds.")
        folds = max(1, panel.shape[0] // max(1, (lookback + hold)))
    if panel.empty or folds < 1:
        out.warnings.append("Insufficient data for walk-forward.")
        return out

    n = panel.shape[0]
    fold_len = n // folds
    by_symbol = {s.symbol: s for s in stocks}

    def _as_date(x):
        return x.date() if hasattr(x, "date") else x

    for k in range(folds):
        start = k * fold_len
        end = n if k == folds - 1 else (k + 1) * fold_len
        sub_index = panel.index[start:end]
        # window bounds as dates — robust whether the panel index holds python
        # dates or pandas Timestamps (avoids hash-mismatch membership bugs)
        lo, hi = _as_date(sub_index[0]), _as_date(sub_index[-1])
        sliced: list[StockData] = []
        for sym, s in by_symbol.items():
            if sym not in panel.columns:
                continue
            bars = [b for b in s.price_history if lo <= b.date <= hi]
            if bars:
                sliced.append(s.model_copy(update={"price_history": bars}))
        out.folds.append(backtest_momentum(sliced, top_n=top_n, lookback=lookback, hold=hold))

    rets = [f.metrics.get("total_return") for f in out.folds if f.metrics]
    sharpes = [f.metrics.get("sharpe_like") for f in out.folds if f.metrics]
    if rets:
        out.aggregate = {
            "mean_fold_return": round(float(np.mean(rets)), 4),
            "worst_fold_return": round(float(np.min(rets)), 4),
            "best_fold_return": round(float(np.max(rets)), 4),
            "mean_sharpe": round(float(np.mean([s for s in sharpes if s is not None] or [0])), 2),
            "positive_folds": int(sum(1 for r in rets if r > 0)),
            "n_folds": len(rets),
        }
    return out
