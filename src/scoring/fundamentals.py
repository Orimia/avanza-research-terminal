"""Fundamental sub-scores: quality, growth, valuation.

Each returns ``None`` when no inputs are available (so coverage can reflect it).
"""
from __future__ import annotations

from src.models.schemas import Fundamentals
from src.scoring import lin, wavg


def quality_score(f: Fundamentals | None) -> float | None:
    if f is None:
        return None
    # net cash (negative net_debt_ebitda) is excellent; >4x is poor
    nd = None
    if f.net_debt_ebitda is not None:
        nd = lin(f.net_debt_ebitda, 4.5, -1.0, 20, 98)
    return wavg([
        (lin(f.gross_margin, 0.15, 0.70, 25, 95), 0.18),
        (lin(f.operating_margin, 0.0, 0.35, 20, 95), 0.20),
        (lin(f.net_margin, 0.0, 0.25, 20, 95), 0.15),
        (lin(f.roic, 0.0, 0.25, 20, 98), 0.18),
        (lin(f.roe, 0.0, 0.30, 20, 95), 0.12),
        (nd, 0.12),
        (lin(f.fcf_margin, -0.05, 0.25, 20, 95), 0.05),
    ])


def growth_score(f: Fundamentals | None) -> float | None:
    if f is None:
        return None
    return wavg([
        (lin(f.revenue_growth, -0.05, 0.35, 15, 95), 0.5),
        (lin(f.eps_growth, -0.10, 0.50, 15, 95), 0.5),
    ])


def valuation_score(f: Fundamentals | None) -> float | None:
    """Cheaper == higher score. Loss-making P/E is penalised, not rewarded."""
    if f is None:
        return None

    def pe_points(pe):
        if pe is None:
            return None
        if pe < 0:
            return 22.0           # losses: not 'cheap'
        return lin(pe, 60, 8, 10, 95)

    return wavg([
        (pe_points(f.pe), 0.22),
        (pe_points(f.forward_pe), 0.13),
        (lin(f.ev_ebitda, 30, 5, 10, 95), 0.18),
        (lin(f.ev_sales, 18, 1, 10, 90), 0.10),
        (lin(f.ps, 18, 1, 10, 90), 0.10),
        (lin(f.pb, 12, 1, 15, 85), 0.07),
        (lin(f.fcf_yield, 0.0, 0.10, 25, 98), 0.20),
    ])
