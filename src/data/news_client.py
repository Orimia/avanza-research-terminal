"""News & catalyst ingestion via RSS (provider news handled in each client).

RSS lets us pull company news, market news and earnings-calendar style feeds
without an API key. Every fetch is logged. Offline -> returns []. Items carry
url + source + timestamp so reports can cite them.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from src.config import get_config
from src.models.schemas import NewsItem
from src.utils.logging import get_logger, log_network_call

log = get_logger("news")

# A few general market feeds; extend via config in future.
MARKET_FEEDS = {
    "Nasdaq": "https://www.nasdaq.com/feed/rssoutbound?category=Markets",
    "CNBC-Markets": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
}


def _parse_feed(url: str, source: str, limit: int) -> list[NewsItem]:
    try:
        import feedparser
    except Exception:  # pragma: no cover
        return []
    cfg = get_config()
    if not cfg.allow_network:
        return []
    log_network_call("rss", url, note=f"feed:{source}")
    try:
        feed = feedparser.parse(url)
    except Exception as exc:  # pragma: no cover - network
        log.warning("RSS parse failed for %s: %s", url, exc)
        return []
    out: list[NewsItem] = []
    for entry in feed.entries[:limit]:
        ts = datetime.now(timezone.utc)
        if getattr(entry, "published_parsed", None):
            import time
            ts = datetime.fromtimestamp(time.mktime(entry.published_parsed), tz=timezone.utc)
        out.append(NewsItem(
            title=getattr(entry, "title", "(no title)"),
            url=getattr(entry, "link", url),
            source=source,
            timestamp=ts,
            summary=(getattr(entry, "summary", "") or "")[:280] or None,
        ))
    return out


def market_news(limit: int = 15) -> list[NewsItem]:
    items: list[NewsItem] = []
    for source, url in MARKET_FEEDS.items():
        items.extend(_parse_feed(url, source, limit))
    items.sort(key=lambda x: x.timestamp, reverse=True)
    return items[:limit]


def company_rss(ticker: str, extra_feeds: Iterable[str] = ()) -> list[NewsItem]:
    """Google-News RSS query for a ticker (best-effort, logged)."""
    cfg = get_config()
    if not cfg.allow_network:
        return []
    query = f"https://news.google.com/rss/search?q={ticker}%20stock&hl=en-US"
    items = _parse_feed(query, "GoogleNews", 8)
    for f in extra_feeds:
        items.extend(_parse_feed(f, "RSS", 5))
    items.sort(key=lambda x: x.timestamp, reverse=True)
    return items
