"""Deterministic memo section builders + institutional lenses.

Everything here is computed from the scored data — no LLM, no invented numbers.
Missing inputs render as ``—missing—`` so the reader always sees coverage gaps.
"""
from __future__ import annotations

from src.models.schemas import Recommendation, StockData, TechnicalSnapshot
from src.utils.dates import fmt_date


# -- formatting ------------------------------------------------------------ #
def _pct(x: float | None, dp: int = 1) -> str:
    return f"{x * 100:.{dp}f}%" if x is not None else "—missing—"


def _x(x: float | None, dp: int = 1) -> str:
    return f"{x:.{dp}f}x" if x is not None else "—missing—"


def _num(x: float | None, dp: int = 1) -> str:
    return f"{x:.{dp}f}" if x is not None else "—missing—"


def _money(x: float | None) -> str:
    if x is None:
        return "—missing—"
    a = abs(x)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if a >= div:
            return f"{x/div:.2f}{suf}"
    return f"{x:.0f}"


# -- A. executive summary -------------------------------------------------- #
def exec_summary(rec: Recommendation) -> str:
    b = rec.score
    return "\n".join([
        "## A. Executive summary",
        f"- **Verdict:** {rec.one_liner}",
        f"- **Action:** **{rec.action.value}**  |  **Confidence:** {rec.confidence.value}",
        f"- **Composite score:** {b.composite:.0f}/100 (coverage {b.coverage*100:.0f}%)",
        f"- **Main reason:** {rec.main_reason}",
        f"- **Biggest risk:** {rec.biggest_risk}",
        f"- **Data freshness:** {rec.data_freshness}  |  "
        f"**Source coverage:** {rec.source_coverage.quality} "
        f"(provider: {rec.source_coverage.provider})",
    ])


# -- B. fundamentals ------------------------------------------------------- #
def fundamentals_section(data: StockData) -> str:
    f = data.fundamentals
    if f is None:
        return "## B. Fundamental analysis\n- _Fundamentals unavailable from source._"
    return "\n".join([
        "## B. Fundamental analysis",
        f"- **Growth:** revenue {_pct(f.revenue_growth)}, EPS {_pct(f.eps_growth)}",
        f"- **Profitability:** gross {_pct(f.gross_margin)}, op {_pct(f.operating_margin)}, "
        f"net {_pct(f.net_margin)}; ROIC {_pct(f.roic)}, ROE {_pct(f.roe)}",
        f"- **Balance sheet:** net debt/EBITDA {_x(f.net_debt_ebitda)}, "
        f"cash {_money(f.cash)}, debt {_money(f.debt)}, FCF {_money(f.fcf)}",
        f"- **Valuation:** P/E {_num(f.pe)} (fwd {_num(f.forward_pe)}), "
        f"EV/EBITDA {_x(f.ev_ebitda)}, EV/Sales {_x(f.ev_sales)}, "
        f"P/S {_x(f.ps)}, P/B {_x(f.pb)}, FCF yield {_pct(f.fcf_yield)}",
        f"- **Earnings quality / guidance:** "
        f"{(data.catalysts.recent_guidance if data.catalysts else None) or '—missing—'}; "
        f"revisions trend {_num(data.catalysts.analyst_revision_trend) if data.catalysts else '—missing—'}",
    ])


# -- C. technical & sentiment ---------------------------------------------- #
def technicals_section(t: TechnicalSnapshot, data: StockData) -> str:
    trend = "uptrend" if (t.price_vs_ma200 or 0) > 0 and (t.price_vs_ma50 or 0) > 0 \
        else "downtrend" if (t.price_vs_ma200 or 0) < 0 else "mixed"
    cat = data.catalysts
    return "\n".join([
        "## C. Technical & sentiment",
        f"- **Trend:** {trend} — vs MA50 {_pct(t.price_vs_ma50)}, vs MA200 {_pct(t.price_vs_ma200)}",
        f"- **Momentum:** 1m {_pct(t.ret_1m)}, 3m {_pct(t.ret_3m)}, "
        f"6m {_pct(t.ret_6m)}, 12m {_pct(t.ret_12m)}; RSI {_num(t.rsi14, 0)}",
        f"- **Support / resistance:** {_num(t.support, 2)} / {_num(t.resistance, 2)} "
        f"(annualised vol {_pct(t.volatility)})",
        f"- **Crowdedness / flow:** volume vs avg {_x(t.volume_anomaly, 2)}; "
        f"short interest {_pct(cat.short_interest_pct) if cat else '—missing—'}",
        f"- **Catalyst timing:** next earnings "
        f"{fmt_date(cat.next_earnings_date) if cat else '—missing—'} "
        f"({(str(cat.days_to_earnings)+'d') if (cat and cat.days_to_earnings is not None) else '—'})",
    ])


# -- D / E bull & bear ----------------------------------------------------- #
def bull_case(rec: Recommendation) -> str:
    rr = rec.risk_reward
    b = rec.score
    drivers = [k for k, v in b.as_dict().items() if v is not None and v >= 62 and k != "Liquidity"]
    return "\n".join([
        "## D. Bull case",
        f"- **Realistic upside:** target {(_num(rr.take_profit,2) if rr else '—')} "
        f"(+{_pct(rr.upside_pct) if rr else '—missing—'}) vs entry {_num(rr.entry,2) if rr else '—'}",
        f"- **What must go right:** sustain strengths in {', '.join(drivers) or 'none clearly dominant'}; "
        f"catalyst confirmation; multiple holds.",
        f"- **Expected upside:** {_pct(rr.upside_pct) if rr else '—missing—'} "
        f"with R/R {(_num(rr.rr_ratio,1)+':1') if rr else '—'}",
    ])


def bear_case(data: StockData, rec: Recommendation) -> str:
    rr = rec.risk_reward
    b = rec.score
    weak = [k for k, v in b.as_dict().items() if v is not None and v <= 45]
    breakers = []
    if rec.technicals and rec.technicals.price_vs_ma200 is not None:
        breakers.append("close below MA200 on volume")
    if data.catalysts and data.catalysts.recent_guidance != "raised":
        breakers.append("a guidance cut or negative revision")
    breakers.append("valuation de-rating if growth disappoints")
    return "\n".join([
        "## E. Bear case",
        f"- **What can go wrong:** {', '.join(weak) or 'no glaring weakness'}; "
        f"{rec.biggest_risk}.",
        f"- **Expected downside:** -{_pct(rr.downside_pct) if rr else '—missing—'} "
        f"to stop {_num(rr.stop_loss,2) if rr else '—'}",
        f"- **Thesis is broken if:** {', '.join(breakers)}.",
    ])


# -- F opportunity cost ---------------------------------------------------- #
def opportunity_cost_section(opp: dict[str, str]) -> str:
    lines = ["## F. Opportunity cost"]
    labels = {"vs_weakest_holding": "vs weakest holding",
              "vs_index": "vs broad index fund", "vs_cash": "vs holding cash"}
    for key, label in labels.items():
        if key in opp:
            lines.append(f"- **{label}:** {opp[key]}")
    if len(lines) == 1:
        lines.append("- _No portfolio loaded — load holdings for full comparison._")
    return "\n".join(lines)


# -- G portfolio fit ------------------------------------------------------- #
def portfolio_fit_section(rec: Recommendation) -> str:
    s = rec.sizing
    if s is None:
        return "## G. Portfolio fit\n- _Sizing not computed (no price/FX)._"
    out = [
        "## G. Portfolio fit",
        f"- **Suggested allocation:** {s.target_weight_pct:.2f}% "
        f"→ ~{s.actual_sek:,.0f} SEK = **{s.shares} whole shares** "
        f"@ {s.price_local:.2f} {s.currency} (≈{s.price_sek:.2f} SEK)",
        f"- **Risk bucket:** {s.risk_bucket}",
        f"- **Sector / country / currency:** {rec.sector or '—'} / "
        f"{rec.country or '—'} / {rec.currency}",
    ]
    if s.currency_risk:
        out.append(f"- **Currency risk:** {s.currency_risk}")
    if s.liquidity_warning:
        out.append(f"- ⚠️ **Liquidity:** {s.liquidity_warning}")
    return "\n".join(out)


# -- H final decision ------------------------------------------------------ #
def final_decision_section(rec: Recommendation) -> str:
    rr = rec.risk_reward
    s = rec.sizing
    action_map = {
        "BUY": "Buy now (scale in if illiquid)", "WATCH": "Wait — add to watchlist for a pullback/catalyst",
        "HOLD": "Hold", "TRIM": "Trim into strength", "SELL": "Sell / exit",
        "AVOID": "Avoid — do not initiate",
    }
    qty = f"{s.shares} shares (~{s.actual_sek:,.0f} SEK)" if s else "size after price/FX confirmed"
    review = "next earnings report (or ~2 weeks, whichever comes first)"
    return "\n".join([
        "## H. Final decision",
        f"- **Instruction:** {action_map.get(rec.action.value, rec.action.value)}",
        f"- **Amount:** {qty if rec.action.value in ('BUY','WATCH') else 'adjust existing position'}",
        f"- **Entry trigger:** {(_num(rr.entry,2)+' area' if rr else '—')} "
        f"(confirm above MA50 for momentum entries)",
        f"- **Exit / stop:** {(_num(rr.stop_loss,2) if rr else '—')}  |  "
        f"**Profit-taking:** {(_num(rr.take_profit,2) if rr else '—')}",
        f"- **Review date / event:** {review} or on thesis-breaking news.",
    ])


# -- I self-attack --------------------------------------------------------- #
def self_attack_section(data: StockData, rec: Recommendation) -> str:
    b = rec.score
    weakest = min(((k, v) for k, v in b.as_dict().items() if v is not None),
                  key=lambda kv: kv[1], default=("coverage", 0))
    mock = " The decision currently rests on **synthetic mock data** — treat as illustrative only." \
        if data.is_mock else ""
    return "\n".join([
        "## I. Self-attack (pre-mortem)",
        f"1. **Weakest assumption:** that {weakest[0].lower()} ({weakest[1]:.0f}) holds; "
        f"coverage is {b.coverage*100:.0f}%.{mock}",
        f"2. **Most likely way it loses money:** {rec.biggest_risk}.",
        f"3. **What the market may already price in:** "
        f"{'rich multiple / crowded momentum' if (b.valuation or 50) < 45 else 'modest expectations'}.",
        "4. **What data would change the decision:** next earnings print, fresh analyst "
        "revisions, insider activity, and any missing fundamentals filled in.",
        f"5. **Better alternative if wrong:** {'a broad index fund or cash' if rec.action.value in ('AVOID','WATCH') else 'rotate to the top-ranked BUY or an index fund'}.",
    ])


# -- institutional lenses -------------------------------------------------- #
_DEFENSIVE = {"Healthcare", "Utilities", "Consumer Staples", "Communication"}
_CYCLICAL = {"Industrials", "Materials", "Energy", "Financials", "Consumer"}


def lenses_section(data: StockData, rec: Recommendation) -> str:
    b = rec.score
    t = rec.technicals
    f = data.fundamentals
    sec = data.sector or "Unknown"
    lines = ["## Institutional lenses"]

    lines.append(f"- **Goldman (equity):** growth {_num(b.growth,0)}, quality {_num(b.quality,0)}, "
                 f"valuation {_num(b.valuation,0)}; "
                 f"upside {_pct(rec.risk_reward.upside_pct) if rec.risk_reward else '—'} / "
                 f"downside {_pct(rec.risk_reward.downside_pct) if rec.risk_reward else '—'}.")
    lines.append(f"- **Morgan Stanley (macro):** {data.currency} exposure; "
                 f"{'rate-sensitive growth' if (b.valuation or 50) < 45 else 'less rate-sensitive'}; "
                 f"sector {sec} {'defensive' if sec in _DEFENSIVE else 'cyclical' if sec in _CYCLICAL else 'neutral'}.")
    lines.append(f"- **McKinsey (strategy):** margins/ROIC imply "
                 f"{'a real moat' if (b.quality or 0) >= 65 else 'limited pricing power'} "
                 f"(gross {_pct(f.gross_margin) if f else '—'}, ROIC {_pct(f.roic) if f else '—'}).")
    lines.append(f"- **BlackRock (portfolio):** vol {_pct(t.volatility)}; "
                 f"adds {'diversification' if sec in _DEFENSIVE else 'beta'}; "
                 "check correlation vs current holdings (see Portfolio Review).")
    lines.append(f"- **Berkshire (owner):** "
                 f"{'durable, cash-generative' if (b.quality or 0) >= 65 and (f and (f.fcf or 0) > 0) else 'quality unproven'}; "
                 f"margin of safety {'thin' if (b.valuation or 50) < 45 else 'reasonable'}.")
    lines.append(f"- **Blackstone (PE):** leverage net debt/EBITDA {_x(f.net_debt_ebitda) if f else '—'}; "
                 f"{'cyclical downside' if sec in _CYCLICAL else 'steadier cash flows'}; "
                 "watch for operational upside / mispricing.")
    lines.append(f"- **Citadel/Point72 (trading):** momentum {_num(b.momentum,0)}, "
                 f"RSI {_num(t.rsi14,0)}, vol-vs-avg {_x(t.volume_anomaly,1)}; "
                 f"{'constructive entry' if (b.momentum or 0) >= 55 else 'wait for setup'}.")
    lines.append("- **Bridgewater (risk regimes):** see stress table below.")
    lines.append(f"- **Activist / short-seller:** strongest bear — {rec.biggest_risk}; "
                 f"{'possible value trap if growth fades' if (b.valuation or 50) < 40 else 'limited obvious accounting red flags in available data'}.")
    lines.append(f"- **CIO (decision):** **{rec.action.value}** at {rec.confidence.value} confidence — "
                 f"{rec.main_reason}.")
    lines.append("")
    lines.append(stress_test_table(data, t))
    return "\n".join(lines)


_SCENARIO_SECTOR = {
    "AI bubble correction": {"Technology": -2, "Communication": -1, "default": 0},
    "Oil shock / ME escalation": {"Energy": 2, "Industrials": -1, "Consumer": -1,
                                   "Materials": -1, "default": -1},
    "Higher-for-longer rates": {"Technology": -2, "Real Estate": -2, "Utilities": -1,
                                 "Financials": 1, "default": -1},
    "Rate-cut rally": {"Technology": 2, "Real Estate": 2, "Consumer": 1,
                        "Financials": -1, "default": 1},
    "Recession scare": {"Healthcare": 1, "Utilities": 1, "Industrials": -2,
                         "Materials": -2, "Consumer": -2, "Financials": -1, "default": -1},
    "USD/SEK swing": {"default": 0},
    "Crypto drawdown": {"Financials": -1, "Technology": -1, "default": 0},
    "Broad risk-off": {"default": -1},
}


def stress_test_table(data: StockData, t: TechnicalSnapshot) -> str:
    sec = data.sector or "Unknown"
    high_beta = (t.volatility or 0.3) >= 0.45
    rows = ["**Bridgewater stress test**", "",
            "| Scenario | Impact | Note |", "|---|---|---|"]
    for scen, mapping in _SCENARIO_SECTOR.items():
        score = mapping.get(sec, mapping.get("default", 0))
        if scen == "USD/SEK swing":
            score = -2 if data.currency == "USD" else -1 if data.currency != "SEK" else 0
        if scen == "Broad risk-off" and high_beta:
            score -= 1
        label = {2: "🟢 Benefits", 1: "🟢 Resilient", 0: "🟡 Neutral",
                 -1: "🟠 Moderate hit", -2: "🔴 High exposure"}.get(max(-2, min(2, score)), "🟡 Neutral")
        note = {
            "USD/SEK swing": f"{data.currency} denominated — SEK value moves with FX",
            "Broad risk-off": f"vol {_pct(t.volatility)} ({'high beta' if high_beta else 'moderate'})",
        }.get(scen, f"{sec} sector sensitivity")
        rows.append(f"| {scen} | {label} | {note} |")
    return "\n".join(rows)
