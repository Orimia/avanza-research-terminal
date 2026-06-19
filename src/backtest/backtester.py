"""Price-history backtest of the ranking strategy.

IMPORTANT — scope & honesty:
  * This backtests the *technical/momentum* portion of the score, because that
    is the only thing we have time-series for. Fundamental scores are single
    snapshots, so a true point-in-time fundamental backtest is NOT possible
    with current data and would be look-ahead biased — we do not fake it.
  * The universe is the set you pass in *today*, so results carry
    **survivorship bias** (delisted/failed names are absent). Treat output as a
    sanity check on the momentum signal, not a track record.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.models.schemas import StockData


@dataclass
class BacktestResult:
    equity_curve: list[tuple[str, float]] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)
    n_rebalances: int = 0
    warnings: list[str] = field(default_factory=list)


def build_price_panel(stocks: list[StockData]) -> pd.DataFrame:
    series = {}
    for s in stocks:
        if s.price_history:
            series[s.symbol] = pd.Series({b.date: b.close for b in s.price_history})
    if not series:
        return pd.DataFrame()
    df = pd.DataFrame(series).sort_index()
    return df.ffill().dropna()


def _max_drawdown(curve: np.ndarray) -> float:
    if curve.size == 0:
        return 0.0
    peak = np.maximum.accumulate(curve)
    return float(-((curve - peak) / peak).min())


def backtest_momentum(stocks: list[StockData], *, top_n: int = 5, lookback: int = 63,
                      hold: int = 21) -> BacktestResult:
    panel = build_price_panel(stocks)
    res = BacktestResult()
    res.warnings.append("Survivorship bias: universe is today's names only.")
    res.warnings.append("Technical-only backtest; fundamentals are not point-in-time.")
    if panel.empty or panel.shape[1] < max(2, top_n) or panel.shape[0] < lookback + hold + 1:
        res.warnings.append("Insufficient aligned history to backtest.")
        return res

    prices = panel
    top_n = min(top_n, prices.shape[1])
    equity = 1.0
    curve_vals = []
    curve = []
    period_rets = []
    pick_rets = []
    i = lookback
    while i + hold < len(prices):
        mom = prices.iloc[i] / prices.iloc[i - lookback] - 1.0
        picks = mom.sort_values(ascending=False).head(top_n).index
        fwd = prices.iloc[i + hold] / prices.iloc[i] - 1.0
        picks_fwd = fwd[picks].dropna()
        if not picks_fwd.empty:
            port_ret = float(picks_fwd.mean())
            equity *= (1 + port_ret)
            period_rets.append(port_ret)
            pick_rets.extend(picks_fwd.tolist())
            curve_vals.append(equity)
            curve.append((str(prices.index[i + hold]), round(equity, 4)))
        i += hold

    if not period_rets:
        res.warnings.append("No completed rebalance periods.")
        return res

    arr = np.asarray(period_rets)
    picks_arr = np.asarray(pick_rets)
    periods_per_year = 252 / hold
    sharpe = (arr.mean() / arr.std() * np.sqrt(periods_per_year)) if arr.std() > 0 else 0.0
    res.equity_curve = curve
    res.n_rebalances = len(period_rets)
    res.metrics = {
        "total_return": round(equity - 1.0, 4),
        "cagr": round(equity ** (periods_per_year / len(arr)) - 1.0, 4),
        "avg_period_return": round(float(arr.mean()), 4),
        "win_rate": round(float((arr > 0).mean()), 4),
        "hit_rate": round(float((picks_arr > 0).mean()), 4),
        "max_drawdown": round(_max_drawdown(np.asarray(curve_vals)), 4),
        "sharpe_like": round(float(sharpe), 2),
        "avg_holding_days": float(hold),
    }
    return res
