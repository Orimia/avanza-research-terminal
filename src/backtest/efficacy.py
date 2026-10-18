"""Signal efficacy: score the engine's OWN past signals against what happened.

Joins ``alerts_log`` (every signal ever emitted, timestamped) with cached price
history and reports, per signal type: how many fired, the median forward return
since, and the hit rate (BUY-ish signals should be followed by gains, SELL-ish
by losses). Cache-only — no network — and brutally honest by construction: if
the sample is thin it says "collecting history", never fakes a stat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from src.storage.db import get_db

BUYISH = {"BUY", "WATCH"}
SELLISH = {"SELL", "TRIM"}
TRACKED = {"NEW_BUY", "BREAKOUT", "RSI_EXTREME", "HOLDING_ACTION", "BIG_MOVE", "STOP_HIT"}
MIN_DAYS = 3          # ignore signals too fresh to judge
MIN_SAMPLE = 3        # below this, report "collecting"


@dataclass
class EfficacyRow:
    signal_type: str
    n: int
    median_fwd_pct: float
    hit_rate: float | None      # None when direction is ambiguous


@dataclass
class EfficacyReport:
    rows: list[EfficacyRow] = field(default_factory=list)
    n_signals_seen: int = 0
    n_scored: int = 0
    note: str = ""


def _entry_and_latest(symbol: str, created: date) -> tuple[float, float, int] | None:
    """(entry close on/after signal date, latest close, days between) from cache."""
    cached = get_db().cache_get(symbol)
    if cached is None:
        return None
    data = cached[0]
    bars = [b for b in data.price_history if b.close > 0]
    if len(bars) < 2:
        return None
    entry = next((b for b in bars if b.date >= created), None)
    if entry is None or entry is bars[-1]:
        return None
    days = (bars[-1].date - entry.date).days
    if days < MIN_DAYS:
        return None
    return entry.close, bars[-1].close, days


def signal_efficacy(limit: int = 400) -> EfficacyReport:
    rep = EfficacyReport()
    per_type: dict[str, list[tuple[float, bool | None]]] = {}
    for a in get_db().alerts_recent(limit):
        if a["type"] not in TRACKED:
            continue
        rep.n_signals_seen += 1
        try:
            created = datetime.fromisoformat(a["created_at"]).date()
        except ValueError:
            continue
        got = _entry_and_latest(a["symbol"], created)
        if got is None:
            continue
        entry, latest, _days = got
        fwd = latest / entry - 1.0
        action = (a.get("action") or "").upper()
        correct: bool | None = None
        if action in BUYISH:
            correct = fwd > 0
        elif action in SELLISH:
            correct = fwd < 0
        per_type.setdefault(a["type"], []).append((fwd, correct))
        rep.n_scored += 1

    for stype, vals in sorted(per_type.items()):
        if len(vals) < MIN_SAMPLE:
            continue
        fwds = sorted(v[0] for v in vals)
        med = fwds[len(fwds) // 2]
        judged = [v[1] for v in vals if v[1] is not None]
        hit = round(sum(judged) / len(judged), 3) if judged else None
        rep.rows.append(EfficacyRow(signal_type=stype, n=len(vals),
                                    median_fwd_pct=round(med * 100, 2), hit_rate=hit))
    if not rep.rows:
        rep.note = (f"Collecting history — {rep.n_signals_seen} signals logged, "
                    f"{rep.n_scored} old enough to score (need ≥{MIN_SAMPLE} per type). "
                    "Judge the engine on data, not vibes; check back in a week.")
    else:
        rep.note = ("Forward return = signal date → latest cached close. "
                    "Small samples — treat as calibration, not proof.")
    return rep
