"""Plain-language layer: turn quant output into sentences a beginner can act on.

Every function here is deterministic and evidence-based — it only rephrases
numbers the engine actually computed (scores, analyst consensus, momentum,
your own cost basis). It never invents facts, and when data is missing it says
less rather than guessing.
"""
from __future__ import annotations

from src.models.schemas import HoldingAnalysis, Recommendation

MAX_BRIEF = 180


def first_sentence(text: str | None, max_len: int = MAX_BRIEF) -> str | None:
    """First sentence of a business description, trimmed for display."""
    if not text or not str(text).strip():
        return None
    s = str(text).strip().split(". ")[0].strip()
    if not s.endswith("."):
        s += "."
    if len(s) > max_len:
        s = s[: max_len - 1].rstrip(" ,;") + "…"
    return s


def why_bullets(rec: Recommendation) -> list[str]:
    """Up to 4 plain-English, evidence-backed reasons behind a rating."""
    out: list[str] = []
    b = rec.score
    if b.quality is not None and b.quality >= 75:
        out.append(f"Excellent business quality — profitability and balance-sheet "
                   f"score {b.quality:.0f}/100")
    elif b.quality is not None and b.quality >= 60:
        out.append(f"Solid business quality ({b.quality:.0f}/100)")
    if b.growth is not None and b.growth >= 70:
        out.append(f"Strong growth (score {b.growth:.0f}/100)")
    a = rec.analyst
    if a and a.target_mean and rec.price:
        up = a.target_mean / rec.price - 1.0
        n = f"{a.n_analysts} analysts" if a.n_analysts else "Analysts"
        out.append(f"{n} target {a.target_mean:,.0f} {rec.currency} on average "
                   f"({up * 100:+.0f}% vs today)")
    t = rec.technicals
    if t and t.ret_3m is not None:
        trend = ""
        if t.price_vs_ma200 is not None:
            trend = (" and trading above its long-term trend" if t.price_vs_ma200 > 0
                     else " but trading below its long-term trend")
        out.append(f"{'Up' if t.ret_3m >= 0 else 'Down'} {abs(t.ret_3m) * 100:.0f}% "
                   f"over 3 months{trend}")
    if b.valuation is not None and b.valuation <= 35:
        out.append(f"Expensive versus its fundamentals (valuation score "
                   f"{b.valuation:.0f}/100) — you pay up for it")
    elif b.valuation is not None and b.valuation >= 65:
        out.append(f"Attractively valued (score {b.valuation:.0f}/100)")
    if rec.dividend_yield and rec.dividend_yield >= 0.02:
        out.append(f"Pays a {rec.dividend_yield * 100:.1f}% dividend")
    if rec.days_to_earnings is not None and 0 <= rec.days_to_earnings <= 14:
        out.append(f"Reports earnings in {rec.days_to_earnings} days — expect bigger swings")
    return out[:4]


def action_sentence(ha: HoldingAnalysis, brief: str | None = None,
                    caution: str | None = None) -> str:
    """One concrete instruction for a holding: what, how much, and why.

    ``caution`` carries the discipline engine's verdict so the tool speaks with
    ONE voice — a recommendation that breaks the user's own rules must say so
    in the same breath, not in a separate section they may never read.
    """
    h = ha.holding
    name = ha.name or h.ticker.upper()
    qty = abs(int(ha.trade_shares))
    sek = abs(float(ha.trade_sek))
    act = ha.action.value

    if act == "BUY":
        what = (f"Buy {qty} more share{'s' if qty != 1 else ''} of {name} "
                f"({h.ticker.upper()}) for about {sek:,.0f} kr"
                if qty else f"Add about {sek:,.0f} kr to {name}")
    elif act == "TRIM":
        what = (f"Sell {qty} of your {h.shares:g} {name} shares "
                f"(about {sek:,.0f} kr) to shrink an oversized position"
                if qty else f"Reduce {name} by about {sek:,.0f} kr")
    elif act == "SELL":
        what = (f"Sell all {h.shares:g} {name} shares (about {sek:,.0f} kr)")
    else:
        what = f"Hold {name} — no change needed"

    why_bits = []
    if ha.score is not None:
        why_bits.append(f"engine score {ha.score.composite:.0f}/100")
    if ha.analyst_upside is not None:
        why_bits.append(f"analysts see {ha.analyst_upside * 100:+.0f}%")
    if ha.unrealized_pct is not None:
        why_bits.append(f"you are {ha.unrealized_pct * 100:+.0f}% on it since buying")
    parts = [what]
    if brief:
        parts.append(brief)
    if why_bits:
        parts.append("Why: " + ", ".join(why_bits) + ".")
    out = " — ".join(parts[:2]) + (f" {parts[2]}" if len(parts) > 2 else "")
    if caution:
        out += f" CAUTION: {caution}"
    return out


def discipline_by_symbol(review, cfg=None) -> dict[str, str]:
    """Map ticker -> discipline warning, for inline coherence in sentences."""
    from src.portfolio.discipline import check_holdings

    out: dict[str, str] = {}
    for f in check_holdings(review, cfg):
        if f.symbol != "PORTFOLIO" and f.symbol not in out:
            out[f.symbol] = f.message
    return out


# -- plain alert translations ------------------------------------------------ #
def translate_signal(stype: str, action: str | None, symbol: str,
                     title: str, state: str | None = None,
                     value: float | None = None) -> str:
    """Rewrite an engine signal as a sentence a non-quant understands."""
    sym = symbol.split(".")[0].upper()
    if stype == "NEW_BUY":
        score = f" (score {value:.0f}/100)" if value else ""
        return (f"New buy idea: {sym} just cleared the quality bar{score}. "
                "Read its memo in the dashboard before acting.")
    if stype == "BREAKOUT":
        return f"{sym} just hit a new multi-month high — momentum is strong."
    if stype == "RSI_EXTREME":
        if action == "TRIM" or (state or "").startswith("overbought"):
            return (f"{sym} looks overheated after a fast run-up — "
                    "hold off on adding; a breather is normal.")
        return (f"{sym} has sold off hard and may be washed out — "
                "no action needed, just be aware.")
    if stype == "MA_CROSS":
        if (state or "") == "above200":
            return f"{sym} climbed back above its long-term trend line — a healthier sign."
        return f"{sym} fell below its long-term trend line — keep an eye on it."
    if stype == "STOP_HIT":
        return (f"{sym} has fallen a long way from its recent high. "
                "Decide whether the story has actually changed — don't just hope.")
    if stype == "TAKEPROFIT_HIT":
        return f"{sym} is well above your purchase price — consider locking in some profit."
    if stype == "BIG_MOVE":
        move = f"{value:+.1f}% today" if value is not None else "sharply today"
        return f"{sym} moved {move} — unusually large; check the news before reacting."
    if stype == "EARNINGS_SOON":
        return f"{sym} reports earnings soon — expect bigger price swings around it."
    if stype == "HOLDING_ACTION":
        tail = title.split(":", 1)[1].strip() if ":" in title else title
        return f"Your holding {sym}: {tail}"
    return title
