"""Order tickets: the exact manual order, ready to type into Avanza.

Turns an actionable recommendation/holding decision into a concrete ticket —
side, quantity, limit price, stop, target, SEK estimate, and a pre-flight
checklist. STRICTLY a planning aid: this module cannot place orders, and the
guardrail tests keep it that way. You execute every order yourself.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.models.schemas import HoldingAnalysis, Recommendation


@dataclass
class OrderTicket:
    symbol: str
    name: str
    side: str                 # BUY / SELL
    qty: int                  # whole shares (0 => SEK-amount order for funds)
    sek_amount: float         # estimated order value in SEK
    limit_price: float | None # local currency; None for fund orders
    currency: str
    stop: float | None = None
    target: float | None = None
    validity: str = "Day"
    note: str = ""
    checklist: list[str] = field(default_factory=list)


def _limit(price: float, side: str) -> float:
    """Marketable limit: pay up/down 0.2% so you fill without chasing."""
    mult = 1.002 if side == "BUY" else 0.998
    return round(price * mult, 2)


def _checklist(side: str, qty: int, sek: float) -> list[str]:
    steps = [
        "Market open and spread reasonable (<0.5%)?",
        f"Size confirmed: ~{sek:,.0f} SEK within today's budget?",
    ]
    if side == "BUY":
        steps.append("Stop level noted BEFORE buying (write it down).")
    else:
        steps.append("Selling on thesis, not on mood? (check the discipline flags)")
    steps.append("Place as LIMIT (never market) · execute manually in Avanza.")
    return steps


def from_recommendation(rec: Recommendation) -> OrderTicket | None:
    """Ticket for a NEW screener BUY (needs price + sizing)."""
    if rec.price is None or rec.sizing is None or rec.sizing.shares <= 0:
        return None
    qty, sek = rec.sizing.shares, rec.sizing.actual_sek
    rr = rec.risk_reward
    return OrderTicket(
        symbol=rec.symbol, name=rec.display_name, side="BUY", qty=qty,
        sek_amount=sek, limit_price=_limit(rec.price, "BUY"), currency=rec.currency,
        stop=round(rr.stop_loss, 2) if rr else None,
        target=round(rr.take_profit, 2) if rr else None,
        note=f"Composite {rec.score.composite:.0f} · {rec.confidence.value} confidence",
        checklist=_checklist("BUY", qty, sek),
    )


def from_holding(ha: HoldingAnalysis) -> OrderTicket | None:
    """Ticket for a proposed holding action (TRIM/SELL/BUY with exact size)."""
    if ha.action.value not in ("BUY", "SELL", "TRIM"):
        return None
    side = "BUY" if ha.action.value == "BUY" else "SELL"
    qty = abs(int(ha.trade_shares))
    sek = abs(float(ha.trade_sek))
    if qty == 0 and sek < 1:
        return None
    price = ha.current_price
    ticket = OrderTicket(
        symbol=ha.holding.symbol, name=ha.name or ha.holding.ticker.upper(),
        side=side, qty=qty, sek_amount=sek,
        limit_price=_limit(price, side) if (price and qty > 0) else None,
        currency=ha.holding.currency, note=ha.trade_note,
        checklist=_checklist(side, qty, sek),
    )
    if qty == 0:  # funds/certs trade as SEK amounts
        ticket.note = (ticket.note + " · place as SEK-amount order").strip(" ·")
    return ticket


def format_ticket(t: OrderTicket) -> str:
    """Plain-text ticket (dashboard code block / Telegram)."""
    px = f"limit {t.limit_price:.2f} {t.currency}" if t.limit_price else "SEK-amount order"
    lines = [
        f"{t.side} {t.qty if t.qty else ''} {t.symbol}".replace("  ", " "),
        f"  {px} · ~{t.sek_amount:,.0f} SEK · validity {t.validity}",
    ]
    if t.stop is not None:
        lines.append(f"  stop {t.stop:.2f} · target {t.target:.2f}" if t.target
                     else f"  stop {t.stop:.2f}")
    if t.note:
        lines.append(f"  {t.note}")
    lines.append("  [manual execution only — this tool never places orders]")
    return "\n".join(lines)
