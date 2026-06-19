"""Import a manually-exported portfolio CSV.

Expected columns (header required):

    ticker,exchange,shares,average_cost,currency,current_price_optional,sector,notes

This reads a CSV the user creates/maintains themselves. It does NOT connect to
Avanza, scrape any page, or use any unofficial API. ``current_price_optional``
may be blank — prices are then fetched from the data layer.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from src.models.schemas import Holding
from src.utils.logging import get_logger

log = get_logger("portfolio")

REQUIRED = {"ticker", "exchange", "shares", "average_cost", "currency"}

# currency -> exchange code (best-effort inference for Avanza imports)
_CCY_EXCHANGE = {"SEK": "ST", "USD": "US", "EUR": "EU", "DKK": "CO", "NOK": "OL"}


def _sv_float(s: str | None) -> float | None:
    """Parse a Swedish/European number: '1 234,56', '1.234,56', '12,5%', '—'."""
    if s is None:
        return None
    t = str(s).strip().replace("\xa0", "").replace(" ", "").replace("%", "")
    t = t.replace("SEK", "").replace("USD", "").replace("EUR", "").strip()
    if not t or t in {"-", "—", "n/a", "N/A"}:
        return None
    # if both separators present, the last one is the decimal sep
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    else:
        t = t.replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _row_to_holding(row: dict) -> Holding | None:
    try:
        cp = row.get("current_price_optional", "").strip()
        return Holding(
            ticker=row["ticker"].strip(),
            exchange=row["exchange"].strip(),
            shares=float(row["shares"]),
            average_cost=float(row["average_cost"]),
            currency=(row.get("currency") or "SEK").strip().upper(),
            current_price=float(cp) if cp else None,
            sector=(row.get("sector") or "").strip() or None,
            notes=(row.get("notes") or "").strip() or None,
        )
    except (KeyError, ValueError) as exc:
        log.warning("Skipping bad portfolio row %s: %s", row, exc)
        return None


def parse_holdings(text: str) -> list[Holding]:
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or not REQUIRED.issubset({f.strip() for f in reader.fieldnames}):
        missing = REQUIRED - {(f or "").strip() for f in (reader.fieldnames or [])}
        raise ValueError(f"CSV missing required columns: {sorted(missing)}")
    holdings = [_row_to_holding(r) for r in reader]
    return [h for h in holdings if h is not None]


def load_holdings_csv(path: str | Path) -> list[Holding]:
    return parse_holdings(Path(path).read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- #
# Avanza export adapter (Swedish columns, ';' delimiter, decimal comma)
# --------------------------------------------------------------------------- #
def _find_col(fieldnames: list[str], candidates: list[str], exclude: tuple = ()) -> str | None:
    low = {(f or "").strip().lower(): f for f in fieldnames}
    for cand in candidates:
        for key, orig in low.items():
            if cand in key and not any(x in key for x in exclude):
                return orig
    return None


def _looks_like_avanza(fieldnames: list[str]) -> bool:
    joined = " ".join((f or "").lower() for f in fieldnames)
    hits = sum(t in joined for t in ("volym", "kortnamn", "marknadsvärde", "gav",
                                     "anskaffnings", "antal", "valuta"))
    return hits >= 2


def parse_avanza_export(text: str) -> list[Holding]:
    """Best-effort parser for Avanza's holdings CSV export.

    Avanza's columns are Swedish and vary by export; we match flexibly and infer
    the exchange from the currency. Results should be reviewed/edited in the app —
    this gets you ~90% there, the in-app editor fixes any mismatch.
    """
    delim = ";" if text.count(";") >= text.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    fns = reader.fieldnames or []
    c_name = _find_col(fns, ["namn", "instrument", "name", "värdepapper"],
                       exclude=("konto", "kort", "depå"))
    c_ticker = _find_col(fns, ["kortnamn", "ticker", "symbol"])
    c_shares = _find_col(fns, ["volym", "antal", "shares", "quantity"])
    c_gav = _find_col(fns, ["gav", "inköpskurs", "anskaffningskurs", "average", "snittkurs"])
    c_acq = _find_col(fns, ["anskaffningsvärde", "anskaffningsv", "cost", "investerat"])
    c_ccy = _find_col(fns, ["valuta", "currency"])
    c_isin = _find_col(fns, ["isin"])

    out: list[Holding] = []
    for row in reader:
        shares = _sv_float(row.get(c_shares)) if c_shares else None
        if not shares:
            continue  # skip cash/empty rows
        ticker = (row.get(c_ticker) or "").strip() if c_ticker else ""
        if not ticker and c_name:
            ticker = (row.get(c_name) or "").strip()
        ticker = ticker.upper().replace(" ", "-")
        if not ticker:
            continue
        ccy = ((row.get(c_ccy) or "SEK").strip().upper() if c_ccy else "SEK") or "SEK"
        avg_cost = _sv_float(row.get(c_gav)) if c_gav else None
        if avg_cost is None and c_acq:  # derive per-share cost from total
            total = _sv_float(row.get(c_acq))
            avg_cost = (total / shares) if total else None
        notes = (row.get(c_isin) or "").strip() if c_isin else None
        out.append(Holding(
            ticker=ticker, exchange=_CCY_EXCHANGE.get(ccy, "ST"),
            shares=shares, average_cost=avg_cost or 0.0, currency=ccy,
            sector=None, notes=(f"ISIN {notes}" if notes else None),
        ))
    return out


def parse_paste(text: str) -> list[Holding]:
    """Parse a pasted plain-text list: 'TICKER SHARES AVGCOST [EXCHANGE] [CCY]'.

    Examples:  'VOLV-B 40 245'  ·  'NVDA 8 95 US USD'
    """
    out: list[Holding] = []
    for line in text.splitlines():
        parts = line.replace(",", " ").split()
        if len(parts) < 3:
            continue
        ticker = parts[0].upper()
        shares = _sv_float(parts[1])
        cost = _sv_float(parts[2])
        if shares is None or cost is None:
            continue
        exchange = parts[3].upper() if len(parts) > 3 and parts[3].isalpha() and len(parts[3]) <= 6 else None
        ccy = parts[4].upper() if len(parts) > 4 else None
        if exchange is None:
            exchange = "ST" if ticker.endswith("-B") or "-" in ticker else "US"
        if ccy is None:
            ccy = {"ST": "SEK", "US": "USD", "EU": "EUR"}.get(exchange, "SEK")
        out.append(Holding(ticker=ticker, exchange=exchange, shares=shares,
                           average_cost=cost, currency=ccy))
    return out


def parse_any(text: str) -> tuple[list[Holding], str]:
    """Auto-detect format. Returns (holdings, detected_format_label)."""
    head = text.lstrip()[:2000].lower()
    try:
        first_line = text.lstrip().splitlines()[0] if text.strip() else ""
    except IndexError:
        first_line = ""
    delim = ";" if first_line.count(";") >= first_line.count(",") else ","
    fieldnames = [f.strip() for f in first_line.split(delim)]

    if REQUIRED.issubset({f.lower() for f in fieldnames}):
        return parse_holdings(text), "native CSV"
    if _looks_like_avanza(fieldnames) or "volym" in head or "kortnamn" in head:
        return parse_avanza_export(text), "Avanza export"
    return parse_paste(text), "pasted list"
