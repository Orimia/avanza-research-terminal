"""Paper-trading ledger: the terminal's own accountable track record.

Every actionable engine signal gets a VIRTUAL fill (never a real order):
NEW_BUY opens a paper position at the current price; a SELL-side holding
action or stop-hit closes it. The dashboard then shows the terminal's live
P&L, so "is this thing actually any good?" has a measured answer instead of
a vibe. Fills are sized like real suggestions (max_new_position_pct of the
portfolio) and marked to market from cached prices.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.config import Config, get_config
from src.storage.db import get_db
from src.utils.currency import to_sek

OPENING_TYPES = {"NEW_BUY"}
CLOSING_ACTIONS = {"SELL", "TRIM"}
CLOSING_TYPES = {"STOP_HIT"}


@dataclass
class TrackRecord:
    n_open: int = 0
    n_closed: int = 0
    realized_sek: float = 0.0
    unrealized_sek: float = 0.0
    hit_rate: float | None = None      # closed trades with pnl > 0
    open_rows: list[dict] = field(default_factory=list)
    closed_rows: list[dict] = field(default_factory=list)


def process_signals(emitted: list, fx: dict[str, float],
                    cfg: Config | None = None) -> int:
    """Record paper fills for this scan's emitted signals. Returns #fills."""
    cfg = cfg or get_config()
    if not cfg.get("profile.paper_trading", True):
        return 0
    from src.data.provider import get_stock_data

    db = get_db()
    pv = cfg.portfolio_value_sek
    target_sek = pv * float(cfg.get("risk.max_new_position_pct", 0.05))
    fills = 0
    for sig in emitted:
        try:
            stype = getattr(sig.type, "value", str(sig.type))
            symbol, action = sig.symbol, (sig.action or "")
            opens = stype in OPENING_TYPES
            closes = (stype in CLOSING_TYPES) or (stype == "HOLDING_ACTION"
                                                  and action in CLOSING_ACTIONS)
            if not (opens or closes):
                continue
            ticker, exchange = symbol.rsplit(".", 1)
            d = get_stock_data(ticker, exchange, enrich_news=False)
            if d.is_mock or d.quote is None:
                continue
            price, ccy = d.quote.price, d.currency
            rate = to_sek(1.0, ccy, fx)
            if opens and db.paper_find_open(symbol) is None:
                qty = int((target_sek / (price * rate)) // 1)
                if qty >= 1:
                    db.paper_open(symbol=symbol, qty=qty, entry_price=price,
                                  currency=ccy, fx_to_sek=rate, source=stype,
                                  note=sig.title[:80])
                    fills += 1
            elif closes:
                pos = db.paper_find_open(symbol)
                if pos is not None:
                    db.paper_close(pos["id"], exit_price=price, fx_to_sek=rate,
                                   note=f"closed by {stype}:{action}")
                    fills += 1
        except Exception:  # pragma: no cover — paper fills must never break a scan
            continue
    return fills


def track_record(fx: dict[str, float]) -> TrackRecord:
    """Mark open paper positions to market (cache-only) and total the ledger."""
    from src.data.provider import get_stock_data

    db = get_db()
    tr = TrackRecord()
    for row in db.paper_positions():
        if row["status"] == "closed":
            tr.n_closed += 1
            tr.realized_sek += float(row["pnl_sek"] or 0.0)
            tr.closed_rows.append(row)
            continue
        tr.n_open += 1
        r = dict(row)
        try:
            ticker, exchange = row["symbol"].rsplit(".", 1)
            d = get_stock_data(ticker, exchange, enrich_news=False)
            if not d.is_mock and d.quote is not None:
                now_sek = row["qty"] * d.quote.price * to_sek(1.0, d.currency, fx)
                r["mark_sek"] = round(now_sek)
                r["unreal_sek"] = round(now_sek - row["entry_sek"])
                tr.unrealized_sek += now_sek - row["entry_sek"]
        except Exception:  # pragma: no cover
            pass
        tr.open_rows.append(r)
    if tr.n_closed:
        wins = sum(1 for r in tr.closed_rows if (r["pnl_sek"] or 0) > 0)
        tr.hit_rate = round(wins / tr.n_closed, 3)
    return tr
