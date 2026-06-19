"""Market-hours awareness for Stockholm / EU / US sessions.

Used to gate intraday scans (only scan when a relevant market is open) while
digests still run at fixed local times. Public holidays are NOT modelled — a
scan on a holiday simply finds no price change and emits nothing, so this is a
safe simplification for v1.
"""
from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

# region -> (tz, open, close) in local exchange time
SESSIONS: dict[str, tuple[str, time, time]] = {
    "nordic": ("Europe/Stockholm", time(9, 0), time(17, 30)),
    "eu": ("Europe/Paris", time(9, 0), time(17, 30)),
    "us": ("America/New_York", time(9, 30), time(16, 0)),
}


def is_market_open(region: str, now: datetime | None = None) -> bool:
    spec = SESSIONS.get(region)
    if spec is None:
        return False
    tz_name, open_t, close_t = spec
    tz = ZoneInfo(tz_name)
    local = now.astimezone(tz) if now else datetime.now(tz)
    if local.weekday() >= 5:  # Sat/Sun
        return False
    return open_t <= local.time() <= close_t


def any_market_open(regions: list[str], now: datetime | None = None) -> bool:
    return any(is_market_open(r, now) for r in regions)


def open_markets(regions: list[str], now: datetime | None = None) -> list[str]:
    return [r for r in regions if is_market_open(r, now)]
