"""Composite scoring + deterministic decision engine."""
from __future__ import annotations

from dataclasses import dataclass

from src.config import Config, get_config
from src.models.schemas import (
    Action,
    Confidence,
    PositionSizing,
    Recommendation,
    RiskReward,
    ScoreBreakdown,
    StockData,
    TechnicalSnapshot,
)
from src.scoring import clamp
from src.scoring.catalysts import catalyst_score
from src.scoring.fundamentals import growth_score, quality_score, valuation_score
from src.scoring.risk import compute_risk_reward, liquidity_score, risk_score
from src.scoring.technicals import compute_technicals, momentum_score
from src.utils.dates import freshness_label

_WEIGHT_KEYS = ["quality", "growth", "momentum", "valuation", "catalyst", "risk"]


@dataclass
class Analysis:
    breakdown: ScoreBreakdown
    technicals: TechnicalSnapshot
    risk_reward: RiskReward | None


def analyze(data: StockData, fx: dict[str, float],
            benchmark_ret_3m: float | None = None, cfg: Config | None = None) -> Analysis:
    cfg = cfg or get_config()
    tech = compute_technicals(data, benchmark_ret_3m)

    subs = {
        "quality": quality_score(data.fundamentals),
        "growth": growth_score(data.fundamentals),
        "momentum": momentum_score(tech, cfg),
        "valuation": valuation_score(data.fundamentals),
        "catalyst": catalyst_score(data.catalysts, data.news),
        "risk": risk_score(data, tech),
    }
    liq = liquidity_score(data, fx)

    weights = cfg.scoring_weights()
    total_w = sum(weights.get(k, 0) for k in _WEIGHT_KEYS)
    num = 0.0
    avail_w = 0.0
    for k in _WEIGHT_KEYS:
        if subs[k] is not None:
            w = weights.get(k, 0)
            num += subs[k] * w
            avail_w += w
    composite = (num / avail_w) if avail_w > 0 else 0.0

    # liquidity gate/penalty (not a weight)
    threshold = float(cfg.get("scoring.liquidity_penalty_below", 40))
    if liq is not None and liq < threshold:
        composite *= 0.70 + 0.30 * (liq / threshold)

    breakdown = ScoreBreakdown(
        quality=_r(subs["quality"]), growth=_r(subs["growth"]),
        valuation=_r(subs["valuation"]), momentum=_r(subs["momentum"]),
        catalyst=_r(subs["catalyst"]), risk=_r(subs["risk"]),
        liquidity=_r(liq), composite=round(clamp(composite), 1),
        coverage=round(avail_w / total_w, 2) if total_w else 0.0,
    )
    rr = compute_risk_reward(data, tech, cfg)
    return Analysis(breakdown=breakdown, technicals=tech, risk_reward=rr)


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 1)


def decide_new(data: StockData, b: ScoreBreakdown, rr: RiskReward | None,
               cfg: Config | None = None,
               analyst_upside: float | None = None) -> tuple[Action, str, str]:
    """Decide BUY / WATCH / AVOID for a *new* opportunity.

    Returns (action, main_reason, biggest_risk).
    """
    cfg = cfg or get_config()
    d = cfg.get("decisions", {})
    buy_min = d.get("buy_min_composite", 68)
    watch_min = d.get("watch_min_composite", 56)
    avoid_max = d.get("avoid_max_composite", 42)
    min_rr = d.get("min_risk_reward", 1.5)

    comp, val, mom, liq = b.composite, b.valuation, b.momentum, b.liquidity
    poor_liq = liq is not None and liq < 30
    extreme_val = val is not None and val < 20
    rr_ok = rr is not None and rr.rr_ratio >= min_rr

    if poor_liq or comp < avoid_max or (extreme_val and (mom is None or mom < 45)):
        action = Action.AVOID
    elif comp >= buy_min and rr_ok and (mom is None or mom >= 50) \
            and (val is None or val >= 30) and not poor_liq:
        action = Action.BUY
    elif comp >= watch_min:
        action = Action.WATCH
    else:
        action = Action.AVOID

    main = _main_reason(b)
    # a name trading meaningfully ABOVE analyst consensus isn't a fresh "buy now" —
    # it's run ahead of fundamentals; wait for a pullback.
    if action == Action.BUY and analyst_upside is not None and analyst_upside < -0.08:
        action = Action.WATCH
        main = (f"{main}; but trades {analyst_upside * 100:+.0f}% vs analyst target — "
                "extended, wait for a pullback")
    return action, main, _biggest_risk(data, b, rr)


def confidence(data: StockData, b: ScoreBreakdown, rr: RiskReward | None,
               cfg: Config | None = None) -> Confidence:
    cfg = cfg or get_config()
    min_rr = cfg.get("decisions.min_risk_reward", 1.5)
    pts = 0
    pts += 2 if b.coverage >= 0.8 else (1 if b.coverage >= 0.6 else 0)
    if b.liquidity is None or b.liquidity >= 60:
        pts += 1
    if rr is not None and rr.rr_ratio >= min_rr:
        pts += 1
    bullish = sum(1 for s in [b.quality, b.growth, b.momentum, b.catalyst] if s is not None and s >= 58)
    bearish = sum(1 for s in [b.quality, b.growth, b.momentum, b.valuation] if s is not None and s <= 42)
    if bullish >= 3 and bearish == 0:
        pts += 2
    elif bullish >= 2:
        pts += 1
    if b.liquidity is not None and b.liquidity < 35:
        pts -= 2
    if b.coverage < 0.5:
        pts -= 2

    level = Confidence.HIGH if pts >= 5 else Confidence.MEDIUM if pts >= 3 else Confidence.LOW
    if data.is_mock and level == Confidence.HIGH:
        level = Confidence.MEDIUM  # never high confidence on synthetic data
    return level


def _main_reason(b: ScoreBreakdown) -> str:
    named = {k: v for k, v in b.as_dict().items() if v is not None and k != "Liquidity"}
    if not named:
        return "Insufficient data to form a strong reason."
    top = sorted(named.items(), key=lambda kv: kv[1], reverse=True)[:2]
    return ", ".join(f"{k.lower()} {v:.0f}" for k, v in top) + f" (composite {b.composite:.0f})"


def _biggest_risk(data: StockData, b: ScoreBreakdown, rr: RiskReward | None) -> str:
    flags = []
    if data.catalysts and data.catalysts.dilution_risk:
        flags.append("dilution risk")
    if b.liquidity is not None and b.liquidity < 40:
        flags.append("thin liquidity")
    if data.catalysts and data.catalysts.days_to_earnings is not None \
            and 0 <= data.catalysts.days_to_earnings <= 14:
        flags.append(f"earnings in {data.catalysts.days_to_earnings}d")
    named = {k: v for k, v in b.as_dict().items() if v is not None}
    if named:
        weakest = min(named.items(), key=lambda kv: kv[1])
        if weakest[1] <= 45:
            flags.append(f"weak {weakest[0].lower()} ({weakest[1]:.0f})")
    if rr is not None and rr.rr_ratio < 1.2:
        flags.append(f"poor R/R ({rr.rr_ratio:.1f})")
    return "; ".join(flags) if flags else "no single dominant risk; broad-market beta"


def build_recommendation(data: StockData, fx: dict[str, float], *,
                         sizing: PositionSizing | None = None,
                         benchmark_ret_3m: float | None = None,
                         cfg: Config | None = None) -> Recommendation:
    cfg = cfg or get_config()
    a = analyze(data, fx, benchmark_ret_3m, cfg)
    au = data.analyst.upside(data.quote.price) if (data.analyst and data.quote) else None
    action, main_reason, biggest_risk = decide_new(data, a.breakdown, a.risk_reward, cfg, au)
    conf = confidence(data, a.breakdown, a.risk_reward, cfg)
    name = data.name or data.ticker
    one_liner = f"{action.value} — {name}: {main_reason}."
    return Recommendation(
        ticker=data.ticker, exchange=data.exchange, name=name,
        action=action, confidence=conf, one_liner=one_liner,
        main_reason=main_reason, biggest_risk=biggest_risk,
        score=a.breakdown, technicals=a.technicals, risk_reward=a.risk_reward,
        analyst=data.analyst, sizing=sizing,
        data_freshness=freshness_label(data.fetched_at),
        source_coverage=data.coverage,
        price=data.quote.price if data.quote else None,
        dividend_yield=data.fundamentals.dividend_yield if data.fundamentals else None,
        days_to_earnings=data.catalysts.days_to_earnings if data.catalysts else None,
        sector=data.sector, country=data.country, currency=data.currency,
    )
