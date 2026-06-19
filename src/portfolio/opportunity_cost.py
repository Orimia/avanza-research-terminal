"""Holding decisions, portfolio exposures and opportunity-cost comparisons."""
from __future__ import annotations

from dataclasses import dataclass, field

from src.config import Config, get_config
from src.models.schemas import (
    Action,
    Confidence,
    Holding,
    HoldingAnalysis,
    Recommendation,
    ScoreBreakdown,
    StockData,
)
from src.scoring.composite import analyze, confidence
from src.utils.currency import to_sek


@dataclass
class PortfolioReview:
    holdings: list[HoldingAnalysis] = field(default_factory=list)
    total_value_sek: float = 0.0
    total_cost_sek: float = 0.0
    sector_exposure: dict[str, float] = field(default_factory=dict)
    country_exposure: dict[str, float] = field(default_factory=dict)
    currency_exposure: dict[str, float] = field(default_factory=dict)
    concentration_top: float = 0.0
    hhi: float = 0.0

    @property
    def unrealized_pct(self) -> float | None:
        # only over holdings that HAVE a cost basis (exclude fixed-value
        # funds/certs whose value would otherwise inflate the gain)
        if self.total_cost_sek <= 0:
            return None
        priced_value = sum(h.value_sek or 0 for h in self.holdings if h.cost_sek)
        return (priced_value - self.total_cost_sek) / self.total_cost_sek

    def weakest(self) -> HoldingAnalysis | None:
        scored = [h for h in self.holdings if h.score is not None]
        if not scored:
            return None
        return min(scored, key=lambda h: h.score.composite)


def decide_holding(data: StockData, b: ScoreBreakdown, weight_pct: float | None,
                   unrealized_pct: float | None, cfg: Config | None = None,
                   kind: str = "stock", analyst_upside: float | None = None) -> tuple[Action, str]:
    cfg = cfg or get_config()
    # Non-equities are NOT rated on the stock thesis (no fundamentals; a broad
    # fund/ETF is the diversifying core, not single-stock concentration risk).
    # They are tracked for price/technical event signals (stop, big move) only.
    if kind != "stock":
        label = {"fund": "Fund", "etf": "ETF", "cert": "Certificate",
                 "crypto": "Crypto"}.get(kind, kind.title())
        return Action.HOLD, (
            f"{label} — held as diversification/thematic exposure. Tracked for price "
            "alerts (stop / big move), not rated on the equity thesis; concentration "
            "caps don't apply."
        )

    d = cfg.get("decisions", {})
    buy_min = d.get("buy_min_composite", 68)
    hold_floor = d.get("hold_floor_composite", 50)
    sell_floor = d.get("sell_floor_composite", 40)
    max_new = float(cfg.get("risk.max_new_position_pct", 0.05)) * 100  # in points

    comp = b.composite
    mom, qual = b.momentum, b.quality
    strong_analyst = analyst_upside is not None and analyst_upside >= 0.15
    au_txt = f"{analyst_upside * 100:+.0f}%" if analyst_upside is not None else "n/a"
    thesis_broken = (mom is not None and mom < 35) and \
                    ((qual is not None and qual < 42) or comp < sell_floor)

    if comp < sell_floor or thesis_broken:
        # don't sell into a name the street still sees big upside on — hold w/ a stop
        if analyst_upside is not None and analyst_upside >= 0.20:
            return Action.HOLD, (
                f"Weak technicals (composite {comp:.0f}) BUT analysts target {au_txt} "
                "upside — hold with a stop rather than selling into weakness."
            )
        return Action.SELL, (
            f"Thesis weakening: composite {comp:.0f} below sell floor {sell_floor} "
            f"(momentum {mom}, quality {qual}); analysts {au_txt}."
        )
    # concentration: flag only past your single-name CEILING (not the buy size),
    # and only if it's actually trimmable (caller downgrades 1-share positions)
    single_cap = float(cfg.get("risk.max_single_position_pct", 0.25)) * 100
    if weight_pct is not None and weight_pct > single_cap:
        return Action.TRIM, (
            f"Oversized at {weight_pct:.1f}% (> {single_cap:.0f}% single-name ceiling) — "
            f"trim to manage concentration (score {comp:.0f}, analysts {au_txt})."
        )
    if comp < hold_floor:
        if strong_analyst:
            return Action.HOLD, (
                f"Mediocre technical score ({comp:.0f}) but analysts target {au_txt} "
                "upside — hold (don't trim a name the street likes)."
            )
        return Action.TRIM, (
            f"Mediocre score ({comp:.0f}), analysts only {au_txt} — trim into stronger ideas."
        )
    if comp >= buy_min and weight_pct is not None and weight_pct < max_new * 0.6:
        return Action.BUY, (
            f"Strong score ({comp:.0f}) and underweight ({weight_pct:.1f}%) — room to add."
        )
    return Action.HOLD, f"Thesis intact (composite {comp:.0f}, analysts {au_txt}); hold."


def analyze_portfolio(holdings: list[Holding], fx: dict[str, float],
                      cfg: Config | None = None) -> PortfolioReview:
    cfg = cfg or get_config()
    from src.data.provider import get_stock_data

    review = PortfolioReview()
    rows: list[HoldingAnalysis] = []
    data_by_symbol = {}
    for h in holdings:
        data = get_stock_data(h.ticker, h.exchange, enrich_news=False)
        data_by_symbol[h.symbol] = data
        price = h.current_price or (data.quote.price if data.quote else None)
        ha = HoldingAnalysis(holding=h, current_price=price, name=h.notes or data.display_name)
        if h.fixed_value_sek is not None:
            # funds/certs we can't price live: value is the user's stated SEK;
            # signals come from the tracked/proxy ticker, unrealized not meaningful
            ha.value_sek = h.fixed_value_sek
            ha.price_sek = ha.price_sek or (to_sek(price, h.currency, fx) if price else None)
        elif price is not None:
            ha.price_sek = to_sek(price, h.currency, fx)
            ha.value_sek = ha.price_sek * h.shares
            ha.cost_sek = to_sek(h.average_cost, h.currency, fx) * h.shares
            if ha.cost_sek:
                ha.unrealized_pct = (ha.value_sek - ha.cost_sek) / ha.cost_sek
        a = analyze(data, fx, cfg=cfg)
        ha.score = a.breakdown
        ha.model_upside = a.risk_reward.upside_pct if a.risk_reward else None
        if data.analyst:
            ha.analyst_target = data.analyst.target_mean
            ha.analyst_upside = data.analyst.upside(price)
        rows.append(ha)

    review.total_value_sek = sum(r.value_sek or 0 for r in rows)
    review.total_cost_sek = sum(r.cost_sek or 0 for r in rows)
    tv = review.total_value_sek or 1.0

    for r in rows:
        data = data_by_symbol[r.holding.symbol]
        r.weight_pct = round((r.value_sek or 0) / tv * 100, 2)
        if r.score:
            r.action, r.rationale = decide_holding(
                data, r.score, r.weight_pct, r.unrealized_pct, cfg,
                kind=r.holding.kind, analyst_upside=r.analyst_upside)
            r.confidence = confidence(data, r.score, None, cfg)
        else:
            r.action, r.rationale, r.confidence = Action.HOLD, "No score available.", Confidence.LOW
        _trade_plan(r, tv, cfg)
        # a TRIM that can't remove a whole share isn't actionable -> hold or sell-all
        if r.action == Action.TRIM and r.holding.whole_share_instrument and r.trade_shares == 0:
            r.action = Action.HOLD
            r.rationale = (f"Overweight ({r.weight_pct:.0f}%) but only "
                           f"{r.holding.shares:g} share(s) — can't trim; keep, or sell the "
                           "whole position if you want the capital elsewhere.")
            r.trade_note = "Hold (single-share position — not trimmable)"
        _bucket(review.sector_exposure, r.holding.sector or r.holding.kind.title(), r.value_sek)
        _bucket(review.currency_exposure, r.holding.currency, r.value_sek)
        _bucket(review.country_exposure, data.country or "Unknown", r.value_sek)

    review.holdings = rows
    weights = [(r.value_sek or 0) / tv for r in rows]
    review.concentration_top = round(max(weights) * 100, 2) if weights else 0.0
    review.hhi = round(sum(w * w for w in weights), 4)
    _to_pct(review.sector_exposure, tv)
    _to_pct(review.country_exposure, tv)
    _to_pct(review.currency_exposure, tv)
    return review


def opportunity_cost(candidate: ScoreBreakdown, weakest: HoldingAnalysis | None,
                     index_proxy: float = 52.0) -> dict[str, str]:
    """Qualitative comparison vs weakest holding / index / cash."""
    out = {}
    c = candidate.composite
    if weakest and weakest.score:
        delta = c - weakest.score.composite
        verdict = "clearly better" if delta > 12 else "marginal" if delta > 0 else "worse"
        out["vs_weakest_holding"] = (
            f"{weakest.holding.ticker} scores {weakest.score.composite:.0f}; "
            f"candidate {c:.0f} ({verdict}, Δ{delta:+.0f})."
        )
    out["vs_index"] = (
        f"Broad index proxy ~{index_proxy:.0f}. Candidate {c:.0f} "
        + ("justifies single-stock risk." if c > index_proxy + 8 else
           "barely beats an index fund — prefer the fund unless conviction rises.")
    )
    out["vs_cash"] = (
        "Beats cash only if risk/reward and catalyst hold; cash is the default when "
        f"composite < ~55 (here {c:.0f})."
    )
    return out


def find_replacements(recs: list[Recommendation], held_symbols: set[str],
                      limit: int = 3) -> list[Recommendation]:
    buys = [r for r in recs if r.action == Action.BUY and r.symbol not in held_symbols]
    buys.sort(key=lambda r: r.score.composite, reverse=True)
    return buys[:limit]


# -- helpers --------------------------------------------------------------- #
def _trade_plan(ha: HoldingAnalysis, total_sek: float, cfg: Config) -> None:
    """Compute the EXACT trade: whole shares (stocks/ETFs) or SEK (funds/certs)."""
    h = ha.holding
    val = ha.value_sek or 0.0
    price_sek = ha.price_sek or 0.0
    max_new = float(cfg.get("risk.max_new_position_pct", 0.05))
    whole = h.whole_share_instrument and price_sek > 0

    if ha.action == Action.HOLD:
        ha.trade_note = "Hold — no change"
        return
    if ha.action == Action.SELL:
        ha.trade_sek = -val
        if whole:
            ha.trade_shares = -int(h.shares)
            ha.trade_note = f"SELL all {h.shares:g} sh (~{val:,.0f} SEK)"
        else:
            ha.trade_note = f"SELL all (~{val:,.0f} SEK)"
        return
    if ha.action == Action.TRIM:
        target = total_sek * max_new
        excess = (val - target) if val > target * 1.05 else val * 0.4
        excess = max(0.0, min(excess, val))
        if whole:
            shares = min(int(h.shares), int(excess // price_sek))
            if shares <= 0:
                ha.trade_note = "Trim < 1 share — optional"
                return
            ha.trade_shares = -shares
            ha.trade_sek = -shares * price_sek
            new_w = (val - shares * price_sek) / total_sek * 100
            ha.trade_note = f"TRIM {shares} sh (~{shares * price_sek:,.0f} SEK) → ~{new_w:.0f}%"
        else:
            ha.trade_sek = -round(excess)
            ha.trade_note = f"TRIM ~{round(excess):,.0f} SEK"
        return
    if ha.action == Action.BUY:  # add to an underweight, strong holding
        add = total_sek * max_new - val
        if add <= 0:
            ha.trade_note = "At target weight — hold"
            return
        if whole:
            shares = int(add // price_sek)
            if shares <= 0:
                ha.trade_note = "Near target — optional top-up"
                return
            ha.trade_shares = shares
            ha.trade_sek = shares * price_sek
            ha.trade_note = f"ADD {shares} sh (~{shares * price_sek:,.0f} SEK)"
        else:
            ha.trade_sek = round(add)
            ha.trade_note = f"ADD ~{round(add):,.0f} SEK"


def _bucket(d: dict[str, float], key: str, value: float | None) -> None:
    d[key] = d.get(key, 0.0) + (value or 0.0)


def _to_pct(d: dict[str, float], total: float) -> None:
    for k in list(d.keys()):
        d[k] = round(d[k] / total * 100, 2) if total else 0.0
