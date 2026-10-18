"""Portfolio intelligence: correlation X-ray, effective bets, Monte Carlo.

Answers the questions position lists hide:
  * Which holdings are secretly the SAME bet? (correlation clusters)
  * How many independent bets do I actually own? (effective-bet count)
  * How exposed am I to the index? (portfolio beta)
  * What does the next year plausibly look like? (bootstrap Monte Carlo)

All computations run on price history already in the local cache — no forecasts,
no fabricated inputs; assets without enough real history are simply excluded and
named. Deterministic (seeded RNG) so results are reproducible.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from src.models.schemas import Holding, StockData

MIN_OVERLAP_DAYS = 120
CLUSTER_CORR = 0.70


@dataclass
class PortfolioXRay:
    tickers: list[str] = field(default_factory=list)
    weights: dict[str, float] = field(default_factory=dict)      # normalised, included only
    corr: pd.DataFrame | None = None
    avg_corr: float | None = None
    effective_bets: float | None = None                          # ENB, 1..N
    beta: float | None = None                                    # vs first benchmark
    clusters: list[list[str]] = field(default_factory=list)      # corr >= 0.70 groups
    excluded: list[str] = field(default_factory=list)            # no usable history
    note: str = ""


@dataclass
class MonteCarlo:
    n_sims: int
    horizon_days: int
    p5: float          # 1y portfolio value multipliers
    p50: float
    p95: float
    prob_loss: float   # P(end value < start)
    mdd_p50: float     # median max drawdown along the path (negative)


def _returns_matrix(datas: dict[str, StockData]) -> pd.DataFrame:
    """Aligned daily log-returns for assets with real price history."""
    series = {}
    for tk, d in datas.items():
        if d is None or d.is_mock or len(d.price_history) < MIN_OVERLAP_DAYS:
            continue
        s = pd.Series([b.close for b in d.price_history],
                      index=[b.date for b in d.price_history])
        series[tk] = np.log(s / s.shift(1))
    if len(series) < 2:
        return pd.DataFrame()
    df = pd.DataFrame(series).dropna(how="any")
    return df.tail(252) if len(df) > 252 else df


def build_xray(holdings: list[Holding], values_sek: dict[str, float],
               datas: dict[str, StockData],
               benchmark: StockData | None = None) -> PortfolioXRay:
    x = PortfolioXRay()
    rets = _returns_matrix(datas)
    x.excluded = [h.ticker for h in holdings if h.ticker not in rets.columns]
    if rets.empty or len(rets) < 60:
        x.note = "Not enough overlapping real price history (need 2+ assets, 60+ days)."
        return x

    x.tickers = list(rets.columns)
    w = np.array([max(0.0, values_sek.get(t, 0.0)) for t in x.tickers])
    if w.sum() <= 0:
        w = np.ones(len(x.tickers))
    w = w / w.sum()
    x.weights = {t: float(round(wi, 4)) for t, wi in zip(x.tickers, w, strict=True)}

    corr = rets.corr()
    x.corr = corr.round(2)
    n = len(x.tickers)
    off = corr.values[np.triu_indices(n, k=1)]
    x.avg_corr = float(round(off.mean(), 3)) if off.size else None
    denom = float(w @ corr.values @ w)
    x.effective_bets = float(round(1.0 / denom, 2)) if denom > 0 else None

    # correlation clusters (connected components at |rho| >= threshold)
    seen: set[int] = set()
    for i in range(n):
        if i in seen:
            continue
        stack, comp = [i], []
        while stack:
            j = stack.pop()
            if j in seen:
                continue
            seen.add(j)
            comp.append(j)
            for k in range(n):
                if k not in seen and corr.values[j, k] >= CLUSTER_CORR:
                    stack.append(k)
        if len(comp) > 1:
            x.clusters.append([x.tickers[j] for j in comp])

    if benchmark is not None and not benchmark.is_mock and len(benchmark.price_history) >= MIN_OVERLAP_DAYS:
        b = pd.Series([bar.close for bar in benchmark.price_history],
                      index=[bar.date for bar in benchmark.price_history])
        b = np.log(b / b.shift(1))
        port = (rets * w).sum(axis=1)
        joined = pd.concat([port, b], axis=1, join="inner").dropna()
        if len(joined) >= 60:
            pv, bv = joined.iloc[:, 0].values, joined.iloc[:, 1].values
            var_b = float(np.var(bv, ddof=1))
            if var_b > 0:
                x.beta = float(round(np.cov(pv, bv, ddof=1)[0, 1] / var_b, 2))
    return x


def monte_carlo(xray: PortfolioXRay, datas: dict[str, StockData], *,
                n_sims: int = 2000, horizon_days: int = 252,
                seed: int = 42) -> MonteCarlo | None:
    """Bootstrap the portfolio's own joint daily returns (correlation preserved)."""
    rets = _returns_matrix({t: datas.get(t) for t in xray.tickers})
    if rets.empty or len(rets) < 60 or not xray.weights:
        return None
    w = np.array([xray.weights.get(t, 0.0) for t in rets.columns])
    if w.sum() <= 0:
        return None
    w = w / w.sum()
    port_daily = (rets.values @ w)                     # historical joint days
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(port_daily), size=(n_sims, horizon_days))
    paths = np.cumsum(port_daily[idx], axis=1)         # log-return paths
    values = np.exp(paths)
    end = values[:, -1]
    running_max = np.maximum.accumulate(values, axis=1)
    mdd = (values / running_max - 1.0).min(axis=1)
    return MonteCarlo(
        n_sims=n_sims, horizon_days=horizon_days,
        p5=float(round(np.percentile(end, 5), 3)),
        p50=float(round(np.percentile(end, 50), 3)),
        p95=float(round(np.percentile(end, 95), 3)),
        prob_loss=float(round(float((end < 1.0).mean()), 3)),
        mdd_p50=float(round(float(np.percentile(mdd, 50)), 3)),
    )
