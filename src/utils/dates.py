"""Date / freshness helpers."""
from __future__ import annotations

from datetime import date, datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def days_between(a: date, b: date) -> int:
    return (a - b).days


def freshness_label(fetched_at: datetime | None) -> str:
    """Human-readable freshness, e.g. 'Fresh (2h ago)' / 'Stale (5d ago)'."""
    if fetched_at is None:
        return "Unknown"
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    delta = now_utc() - fetched_at
    secs = delta.total_seconds()
    if secs < 3600:
        age = f"{int(secs // 60)}m ago"
    elif secs < 86400:
        age = f"{int(secs // 3600)}h ago"
    else:
        age = f"{int(secs // 86400)}d ago"
    if secs < 6 * 3600:
        tag = "Fresh"
    elif secs < 36 * 3600:
        tag = "Recent"
    else:
        tag = "Stale"
    return f"{tag} ({age})"


def fmt_date(d: date | datetime | None) -> str:
    if d is None:
        return "—"
    if isinstance(d, datetime):
        return d.strftime("%Y-%m-%d %H:%M")
    return d.strftime("%Y-%m-%d")
