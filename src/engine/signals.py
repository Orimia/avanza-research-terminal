"""Signal schema + pure detector functions.

Detectors take current data (+ optional holding context) and return a
:class:`Signal` describing the *current* state. The scanner decides whether to
actually emit it by comparing ``state_value`` against stored state, so detectors
stay pure and testable. Fields:

  * ``alert_worthy``  — this state is one we'd notify about (else just recorded)
  * ``seed_silently`` — on first-ever observation, record state but don't alert
                        (used for noisy technical signals to avoid a first-run blast)
  * ``recurring_daily`` — re-arm once per day even if state is unchanged (moves)
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from src.models.schemas import Action, Holding, ScoreBreakdown, StockData, TechnicalSnapshot


class SignalType(str, Enum):
    NEW_BUY = "NEW_BUY"
    HOLDING_ACTION = "HOLDING_ACTION"
    STOP_HIT = "STOP_HIT"
    TAKEPROFIT_HIT = "TAKEPROFIT_HIT"
    BIG_MOVE = "BIG_MOVE"
    BREAKOUT = "BREAKOUT"
    RSI_EXTREME = "RSI_EXTREME"
    MA_CROSS = "MA_CROSS"
    EARNINGS_SOON = "EARNINGS_SOON"


class Signal(BaseModel):
    symbol: str
    ticker: str
    exchange: str
    type: SignalType
    action: str = "REVIEW"
    severity: str = "info"            # info / warn / critical
    title: str = ""
    detail: str = ""
    value: Optional[float] = None
    dedup_key: str = ""
    state_value: str = ""
    alert_worthy: bool = True
    seed_silently: bool = False
    recurring_daily: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


def _base(data: StockData, type_: SignalType, key_suffix: str) -> dict:
    return dict(symbol=data.symbol, ticker=data.ticker, exchange=data.exchange,
                type=type_, dedup_key=f"{data.symbol}|{key_suffix}")


# --------------------------------------------------------------------------- #
# Intraday / price-based detectors
# --------------------------------------------------------------------------- #
def big_move(data: StockData, big_move_pct: float, today: str) -> Optional[Signal]:
    closes = data.closes()
    if len(closes) < 2 or closes[-2] <= 0:
        return None
    move = closes[-1] / closes[-2] - 1.0
    if abs(move) < big_move_pct:
        return None
    sev = "warn" if abs(move) >= 1.5 * big_move_pct else "info"
    arrow = "▲" if move > 0 else "▼"
    return Signal(**_base(data, SignalType.BIG_MOVE, "BIG_MOVE"),
                  action="REVIEW", severity=sev, value=round(move, 4),
                  title=f"{arrow} {data.ticker} {move:+.1%} on the day",
                  detail=f"{data.name or data.ticker} moved {move:+.1%} to "
                         f"{closes[-1]:.2f} {data.currency}.",
                  state_value=today, recurring_daily=True)


def breakout(data: StockData, lookback: int) -> Optional[Signal]:
    closes = data.closes()
    if len(closes) < lookback + 1:
        return None
    prior_high = max(closes[-lookback - 1:-1])
    at_high = closes[-1] >= prior_high
    state = "breakout" if at_high else "normal"
    return Signal(**_base(data, SignalType.BREAKOUT, "BREAKOUT"),
                  action="WATCH", severity="info", value=round(closes[-1], 2),
                  title=f"{data.ticker} new {lookback}-bar high",
                  detail=f"{data.name or data.ticker} broke above its "
                         f"{lookback}-bar high ({prior_high:.2f}) at {closes[-1]:.2f}.",
                  state_value=state, alert_worthy=at_high, seed_silently=True)


def rsi_extreme(data: StockData, tech: TechnicalSnapshot,
                overbought: float, oversold: float) -> Optional[Signal]:
    if tech.rsi14 is None:
        return None
    if tech.rsi14 >= overbought:
        zone, action, sev = "overbought", "TRIM", "info"
        title = f"RSI {tech.rsi14:.0f} overbought — {data.ticker}"
    elif tech.rsi14 <= oversold:
        zone, action, sev = "oversold", "WATCH", "info"
        title = f"RSI {tech.rsi14:.0f} oversold — {data.ticker}"
    else:
        zone, action, sev, title = "neutral", "HOLD", "info", ""
    return Signal(**_base(data, SignalType.RSI_EXTREME, "RSI"),
                  action=action, severity=sev, value=round(tech.rsi14, 1),
                  title=title, detail=f"RSI(14) is {tech.rsi14:.0f}.",
                  state_value=zone, alert_worthy=zone != "neutral", seed_silently=True)


def ma_cross(data: StockData, tech: TechnicalSnapshot) -> Optional[Signal]:
    if tech.price_vs_ma200 is None:
        return None
    above = tech.price_vs_ma200 >= 0
    state = "above200" if above else "below200"
    action = "WATCH" if above else "REVIEW"
    title = (f"{data.ticker} reclaimed its 200-day MA" if above
             else f"{data.ticker} lost its 200-day MA")
    return Signal(**_base(data, SignalType.MA_CROSS, "MA200"),
                  action=action, severity="info",
                  value=round(tech.price_vs_ma200, 4), title=title,
                  detail=f"Price is {tech.price_vs_ma200:+.1%} vs the 200-day MA.",
                  state_value=state, seed_silently=True)


def stop_take(data: StockData, holding: Holding, stop_pct: float,
              tp_pct: float) -> list[Signal]:
    """Trailing-stop (drawdown from recent high) and cost-based take-profit
    for a held position. States re-arm ('ok' -> 'triggered') so each crossing
    alerts once.
    """
    out: list[Signal] = []
    if not data.quote:
        return out
    px = data.quote.price
    closes = data.closes()
    if closes:
        high = max(closes[-60:]) if len(closes) >= 2 else closes[-1]
        stop = high * (1 - stop_pct)
        hit = px <= stop
        out.append(Signal(**_base(data, SignalType.STOP_HIT, "STOP"),
                          action="SELL" if hit else "HOLD", severity="critical",
                          value=round(px, 2),
                          title=f"{data.ticker} {px / high - 1:+.0%} from high — stop hit",
                          detail=f"{data.name or data.ticker} at {px:.2f} {data.currency} is "
                                 f"{px / high - 1:+.1%} from its recent high {high:.2f} "
                                 f"(trailing stop {stop:.2f}). Reassess / exit.",
                          state_value="triggered" if hit else "ok",
                          alert_worthy=hit, seed_silently=False))
    if holding.average_cost > 0:
        gain = px / holding.average_cost - 1.0
        hit = gain >= tp_pct
        out.append(Signal(**_base(data, SignalType.TAKEPROFIT_HIT, "TP"),
                          action="TRIM" if hit else "HOLD", severity="warn",
                          value=round(gain, 4),
                          title=f"{data.ticker} {gain:+.0%} vs cost — take profit?",
                          detail=f"Up {gain:+.1%} from average cost {holding.average_cost:.2f}; "
                                 "consider trimming to lock in gains.",
                          state_value="triggered" if hit else "ok",
                          alert_worthy=hit, seed_silently=False))
    return out


# --------------------------------------------------------------------------- #
# Fundamental / decision detectors (digest scans)
# --------------------------------------------------------------------------- #
def new_buy(data: StockData, b: ScoreBreakdown, action: Action,
            min_composite: float) -> Optional[Signal]:
    is_buy = action == Action.BUY and b.composite >= min_composite
    state = "BUY" if is_buy else "not-buy"
    return Signal(**_base(data, SignalType.NEW_BUY, "NEW_BUY"),
                  action="BUY", severity="warn", value=round(b.composite, 1),
                  title=f"New BUY — {data.ticker} (score {b.composite:.0f})",
                  detail=f"{data.name or data.ticker} entered BUY range "
                         f"(composite {b.composite:.0f}).",
                  state_value=state, alert_worthy=is_buy, seed_silently=False)


def holding_action(data: StockData, action: Action, rationale: str,
                   trade: str = "") -> Optional[Signal]:
    worthy = action in (Action.TRIM, Action.SELL, Action.BUY)
    sev = "critical" if action == Action.SELL else "warn" if action == Action.TRIM else "info"
    title = f"{data.ticker}: {trade}" if trade else f"{data.ticker}: {action.value} (holding)"
    return Signal(**_base(data, SignalType.HOLDING_ACTION, "HOLD_ACTION"),
                  action=action.value, severity=sev, title=title,
                  detail=f"{trade}. {rationale}" if trade else rationale,
                  state_value=action.value, alert_worthy=worthy, seed_silently=False)


def earnings_soon(data: StockData, within_days: int) -> Optional[Signal]:
    c = data.catalysts
    if not c or c.days_to_earnings is None or c.next_earnings_date is None:
        return None
    dte = c.days_to_earnings
    worthy = 0 <= dte <= within_days
    return Signal(**_base(data, SignalType.EARNINGS_SOON, "EARNINGS"),
                  action="REVIEW", severity="info", value=float(dte),
                  title=f"📅 {data.ticker} earnings in {dte}d ({c.next_earnings_date})",
                  detail=f"{data.name or data.ticker} reports on {c.next_earnings_date}. "
                         "Expect volatility; size accordingly.",
                  state_value=c.next_earnings_date.isoformat(),
                  alert_worthy=worthy, seed_silently=False)
