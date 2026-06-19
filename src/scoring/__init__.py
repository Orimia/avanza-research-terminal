"""Deterministic scoring engine.

All sub-scores are on a 0–100 scale where **higher is better** (including the
risk score, where higher == safer). Missing inputs return ``None`` and are
excluded from the weighted composite, which is renormalised over whatever data
is available. Nothing here calls an LLM.
"""
from __future__ import annotations


def clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def lin(x: float | None, x0: float, x1: float, y0: float = 0.0, y1: float = 100.0) -> float | None:
    """Linear map x in [x0,x1] -> [y0,y1], clamped. Supports x0>x1 (inverse)."""
    if x is None:
        return None
    if x0 == x1:
        return clamp((y0 + y1) / 2, min(y0, y1), max(y0, y1))
    t = (x - x0) / (x1 - x0)
    t = max(0.0, min(1.0, t))
    return y0 + t * (y1 - y0)


def avg(parts: list[float | None]) -> float | None:
    vals = [p for p in parts if p is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def wavg(pairs: list[tuple[float | None, float]]) -> float | None:
    """Weighted average over (value, weight); skips None values."""
    num = 0.0
    den = 0.0
    for val, w in pairs:
        if val is None:
            continue
        num += val * w
        den += w
    return (num / den) if den > 0 else None
