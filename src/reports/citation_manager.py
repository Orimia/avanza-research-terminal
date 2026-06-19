"""Citation manager — every factual news/filing claim must carry a source.

Collects :class:`NewsItem` sources, de-duplicates by URL, and renders a numbered
reference list with source name + timestamp + link for the memo footer.
"""
from __future__ import annotations

from src.models.schemas import NewsItem
from src.utils.dates import fmt_date


class CitationManager:
    def __init__(self) -> None:
        self._by_url: dict[str, NewsItem] = {}
        self._order: list[str] = []

    def add(self, items: list[NewsItem]) -> None:
        for it in items:
            if it.url not in self._by_url:
                self._by_url[it.url] = it
                self._order.append(it.url)

    def index_of(self, url: str) -> int | None:
        return (self._order.index(url) + 1) if url in self._order else None

    @property
    def count(self) -> int:
        return len(self._order)

    @property
    def has_mock(self) -> bool:
        return any("mock.local" in u for u in self._order)

    def render(self) -> str:
        if not self._order:
            return "_No sources captured (data unavailable or offline)._"
        lines = ["**Sources**", ""]
        for i, url in enumerate(self._order, start=1):
            it = self._by_url[url]
            tag = " _(synthetic/mock)_" if "mock.local" in url else ""
            lines.append(f"{i}. [{it.source}] {it.title} — {fmt_date(it.timestamp)} "
                         f"<{url}>{tag}")
        return "\n".join(lines)
