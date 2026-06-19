"""Risk & liquidity scoring, risk/reward construction, drawdown, classification.

Risk score is on the *safety* convention: higher == lower risk, so it adds
positively to the composite.
"""
from __future__ import annotations

import math

import numpy as np

from src.models.schemas import RiskReward, StockData, TechnicalSnapshot
from src.scoring import clamp, lin, wavg
from src.utils.currency import to_sek


def max_drawdown(closes: list[float]) -> float | None:
    if len(closes) < 30:
        return None
    arr = np.asarray(closes, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = (arr - peak) / peak
    return float(-dd.min())  # positive number, e.g. 0.35 == 35%


def liquidity_score(data: StockData, fx: dict[str, float]) -> float | None:
    if not data.quote or data.quote.avg_turnover is None:
        return None
    turn_sek = to_sek(data.quote.avg_turnover, data.currency, fx)
    if turn_sek <= 0:
        return 0.0
    # 1 MSEK/day -> low, 200 MSEK/day -> excellent (log scale)
    return lin(math.log10(turn_sek), 6.0, 8.3, 10, 99)


def risk_score(data: StockData, tech: TechnicalSnapshot) -> float | None:
    parts: list[tuple[float | None, float]] = []
    parts.append((lin(tech.volatility, 0.60, 0.12, 10, 95), 0.40))
    dd = max_drawdown(data.closes())
    parts.append((lin(dd, 0.70, 0.10, 15, 95), 0.25))
    if data.fundamentals and data.fundamentals.net_debt_ebitda is not None:
        parts.append((lin(data.fundamentals.net_debt_ebitda, 5.0, -1.0, 20, 95), 0.25))
    base = wavg(parts)
    if base is None:
        return None
    if data.catalysts and data.catalysts.dilution_risk:
        base -= 12
    return clamp(base)


def is_high_risk(data: StockData, tech: TechnicalSnapshot, cfg) -> bool:
    hv = float(cfg.get("risk.high_volatility_annual", 0.45))
    if tech.volatility is not None and tech.volatility >= hv:
        return True
    if data.fundamentals and data.fundamentals.net_debt_ebitda is not None \
            and data.fundamentals.net_debt_ebitda > 4.0:
        return True
    return bool(data.catalysts and data.catalysts.dilution_risk)


def compute_risk_reward(data: StockData, tech: TechnicalSnapshot, cfg) -> RiskReward | None:
    if not data.quote:
        return None
    entry = data.quote.price
    if entry <= 0:
        return None
    default_stop = float(cfg.get("risk.default_stop_pct", 0.12))
    default_tp = float(cfg.get("risk.default_take_profit_pct", 0.25))

    vol = tech.volatility or 0.30
    stop_pct = min(0.28, max(default_stop, vol * 0.38))
    stop = entry * (1 - stop_pct)
    # prefer a real resistance target if it sits meaningfully above entry
    if tech.resistance and tech.resistance > entry * 1.05:
        take_profit = tech.resistance
    else:
        take_profit = entry * (1 + max(default_tp, stop_pct * 2.0))

    upside = (take_profit - entry) / entry
    downside = (entry - stop) / entry
    rr = upside / downside if downside > 0 else 0.0
    return RiskReward(
        entry=round(entry, 2), stop_loss=round(stop, 2), take_profit=round(take_profit, 2),
        upside_pct=round(upside, 4), downside_pct=round(downside, 4), rr_ratio=round(rr, 2),
    )
