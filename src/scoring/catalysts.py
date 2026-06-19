"""Catalyst sub-score: revisions, insiders, buybacks, guidance, news, earnings."""
from __future__ import annotations

from src.models.schemas import Catalysts, NewsItem
from src.scoring import clamp, lin


def catalyst_score(c: Catalysts | None, news: list[NewsItem] | None) -> float | None:
    have_any = c is not None or bool(news)
    if not have_any:
        return None

    score = 50.0
    if c is not None:
        if c.analyst_revision_trend is not None:
            score += (lin(c.analyst_revision_trend, -1, 1, -18, 18) or 0)
        if c.insider_net_buying is not None:
            if c.insider_net_buying > 0:
                score += 8
            elif c.insider_net_buying < 0:
                score -= 6
        if c.buyback_active:
            score += 7
        if c.dilution_risk:
            score -= 14
        if c.recent_guidance == "raised":
            score += 12
        elif c.recent_guidance == "cut":
            score -= 15
        elif c.recent_guidance == "maintained":
            score += 2
        # near-term earnings is a live catalyst (uncertainty handled in risk/confidence)
        if c.days_to_earnings is not None and c.days_to_earnings <= 21:
            score += 6
        if c.short_interest_pct is not None and c.short_interest_pct > 0.15:
            score -= 5  # overhang; could squeeze but treat as risk by default

    if news:
        sents = [n.sentiment for n in news if n.sentiment is not None]
        if sents:
            avg_sent = sum(sents) / len(sents)
            score += (lin(avg_sent, -0.6, 0.6, -12, 12) or 0)

    return clamp(score)
