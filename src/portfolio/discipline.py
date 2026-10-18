"""Personal discipline engine.

Encodes the investor's own rules (config ``profile:``) and argues back when a
proposed action matches a known failure mode:

    averaging-down   BUY more of a position that's already >10% under water
    churn            more proposed changes than the monthly trade budget
    quality-dump     SELL a high-quality name at the lows (panic exit)
    fomo-entry       new BUY that is RSI-extended or far above its 50-day MA

It only ever WARNS — it never blocks and never trades. The point is a second
opinion tuned to the user's history, delivered before the mistake, not after.
"""
from __future__ import annotations

from dataclasses import dataclass

from src.config import Config, get_config
from src.models.schemas import Action, Recommendation

SEVERITY_ORDER = {"warn": 0, "info": 1}


@dataclass
class DisciplineFlag:
    rule: str
    symbol: str
    severity: str      # warn | info
    message: str


def check_holdings(review, cfg: Config | None = None) -> list[DisciplineFlag]:
    """Rules over the CURRENT portfolio review's proposed actions."""
    cfg = cfg or get_config()
    p = cfg.get("profile", {}) or {}
    flags: list[DisciplineFlag] = []

    acts = [h for h in review.holdings if h.action != Action.HOLD]
    budget = int(p.get("max_trades_per_month", 6))
    if len(acts) > budget:
        flags.append(DisciplineFlag(
            rule="churn", symbol="PORTFOLIO", severity="warn",
            message=(f"{len(acts)} changes proposed vs your budget of {budget}/month — "
                     "churn is the enemy on a small account; do the top 1-2 only."),
        ))

    allow_avg = bool(p.get("allow_averaging_down", False))
    q_floor = float(p.get("sell_quality_floor", 65))
    for h in review.holdings:
        upct = h.unrealized_pct
        if (h.action == Action.BUY and not allow_avg
                and upct is not None and upct < -0.10):
            flags.append(DisciplineFlag(
                rule="averaging-down", symbol=h.holding.ticker.upper(), severity="warn",
                message=(f"Adding to a {upct * 100:.0f}% loser is averaging down — "
                         "your rule requires a NEW thesis, not a lower entry price."),
            ))
        if (h.action == Action.SELL and h.score is not None
                and (h.score.quality or 0) >= q_floor
                and upct is not None and upct <= -0.20):
            flags.append(DisciplineFlag(
                rule="quality-dump", symbol=h.holding.ticker.upper(), severity="warn",
                message=(f"Selling quality (score {h.score.quality:.0f}) down "
                         f"{upct * 100:.0f}% — confirm the THESIS broke, not just the price."),
            ))
    flags.sort(key=lambda f: SEVERITY_ORDER.get(f.severity, 9))
    return flags


def check_new_buys(recs: list[Recommendation], cfg: Config | None = None) -> list[DisciplineFlag]:
    """FOMO check over screener BUY ideas (extended entries)."""
    cfg = cfg or get_config()
    fomo_rsi = float(cfg.get("profile.fomo_rsi", 75))
    flags: list[DisciplineFlag] = []
    for r in recs:
        if r.action != Action.BUY or r.technicals is None:
            continue
        rsi = r.technicals.rsi14
        ext = r.technicals.price_vs_ma50
        if (rsi is not None and rsi >= fomo_rsi) or (ext is not None and ext > 0.12):
            why = f"RSI {rsi:.0f}" if (rsi is not None and rsi >= fomo_rsi) \
                else f"{ext * 100:+.0f}% above its 50-day MA"
            flags.append(DisciplineFlag(
                rule="fomo-entry", symbol=r.ticker.upper(), severity="info",
                message=f"Extended entry ({why}) — chasing; wait for a pullback.",
            ))
    return flags


def profile_summary(cfg: Config | None = None) -> str:
    cfg = cfg or get_config()
    p = cfg.get("profile", {}) or {}
    return (f"max {p.get('max_trades_per_month', 6)} trades/mo · "
            f"hold ≥{p.get('min_holding_days', 30)}d · "
            f"no averaging down · no entries above RSI {p.get('fomo_rsi', 75)} · "
            f"don't dump quality (score ≥{p.get('sell_quality_floor', 65)}) at the lows")
