"""Technical analysis: momentum, moving averages, RSI, volatility, S/R."""
from __future__ import annotations

import numpy as np

from src.models.schemas import StockData, TechnicalSnapshot
from src.scoring import lin, wavg


def _ret(closes: list[float], lookback: int) -> float | None:
    if len(closes) <= lookback or closes[-lookback - 1] <= 0:
        return None
    return closes[-1] / closes[-lookback - 1] - 1.0


def _sma(closes: list[float], window: int) -> float | None:
    if len(closes) < window:
        return None
    return float(np.mean(closes[-window:]))


def _rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    diff = np.diff(np.asarray(closes[-(period + 1):], dtype=float))
    gains = np.where(diff > 0, diff, 0.0)
    losses = np.where(diff < 0, -diff, 0.0)
    avg_gain = gains.mean()
    avg_loss = losses.mean()
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def _volatility(closes: list[float]) -> float | None:
    if len(closes) < 30:
        return None
    arr = np.asarray(closes[-252:], dtype=float)
    rets = np.diff(np.log(arr))
    return float(np.std(rets) * np.sqrt(252))


def compute_technicals(data: StockData, benchmark_ret_3m: float | None = None) -> TechnicalSnapshot:
    closes = data.closes()
    if len(closes) < 25:
        return TechnicalSnapshot()
    price = closes[-1]
    ma50 = _sma(closes, 50)
    ma200 = _sma(closes, 200)
    window = closes[-60:]
    ret_3m = _ret(closes, 63)
    rel = (ret_3m - benchmark_ret_3m) if (ret_3m is not None and benchmark_ret_3m is not None) else None
    latest_vol = data.price_history[-1].volume if data.price_history else None
    avg_vol = float(np.mean([b.volume for b in data.price_history[-20:]])) if data.price_history else None

    yr = closes[-252:] if len(closes) >= 60 else closes
    hi52, lo52 = float(max(yr)), float(min(yr))
    in_range = (price - lo52) / (hi52 - lo52) if hi52 > lo52 else None

    return TechnicalSnapshot(
        ret_1m=_ret(closes, 21), ret_3m=ret_3m,
        ret_6m=_ret(closes, 126), ret_12m=_ret(closes, 252),
        ma20=_sma(closes, 20), ma50=ma50, ma200=ma200,
        price_vs_ma50=(price / ma50 - 1.0) if ma50 else None,
        price_vs_ma200=(price / ma200 - 1.0) if ma200 else None,
        rsi14=_rsi(closes), rel_strength=rel,
        volume_anomaly=(latest_vol / avg_vol) if (latest_vol and avg_vol) else None,
        support=float(min(window)), resistance=float(max(window)),
        volatility=_volatility(closes),
        wk52_high=hi52, wk52_low=lo52, pct_in_range=in_range,
    )


def momentum_score(t: TechnicalSnapshot, cfg) -> float | None:
    sweet = cfg.get("scoring.rsi_sweet_spot", [45, 65])
    overbought = cfg.get("scoring.rsi_overbought", 75)

    def rsi_points(r):
        if r is None:
            return None
        if sweet[0] <= r <= sweet[1]:
            return 85.0
        if r > overbought:
            return 45.0          # extended
        if r < 30:
            return 35.0          # weak / oversold
        return 65.0

    ma50_pts = None if t.price_vs_ma50 is None else (75.0 if t.price_vs_ma50 > 0 else 35.0)
    ma200_pts = None if t.price_vs_ma200 is None else (75.0 if t.price_vs_ma200 > 0 else 35.0)
    rel_pts = lin(t.rel_strength, -0.15, 0.20, 25, 90) if t.rel_strength is not None else None

    return wavg([
        (lin(t.ret_1m, -0.15, 0.20, 25, 88), 0.10),
        (lin(t.ret_3m, -0.25, 0.35, 15, 95), 0.25),
        (lin(t.ret_6m, -0.30, 0.50, 15, 95), 0.20),
        (lin(t.ret_12m, -0.40, 0.80, 15, 95), 0.15),
        (ma50_pts, 0.10), (ma200_pts, 0.10),
        (rsi_points(t.rsi14), 0.05), (rel_pts, 0.05),
    ])
