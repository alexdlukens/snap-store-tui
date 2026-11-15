"""Search request models and row conversion."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from snap_python.schemas.store.search import (
    ArchSearchItem,
    PaginatedSnapSearchResponse,
    SearchResponse,
)

from store_tui.widgets.results_table import ResultRow, rows_from_search_response

SEARCH_FIELDS = [
    "title",
    "store-url",
    "summary",
    "version",
    "confinement",
    "publisher",
    "revision",
]


@dataclass(frozen=True)
class SearchFilters:
    """Optional store filters. Unset values are omitted from the request."""

    confinement: str | None = None
    category: str | None = None
    publisher: str | None = None
    architecture: str | None = None
    channel: str | None = None
    name_startswith: str | None = None
    featured: bool | None = None

    @property
    def advanced(self) -> bool:
        """True when a filter needs the full ``find()`` endpoint."""
        return any(
            value is not None
            for value in (
                self.category,
                self.publisher,
                self.channel,
                self.name_startswith,
                self.featured,
            )
        )

    @property
    def is_empty(self) -> bool:
        return all(
            value is None
            for value in (
                self.confinement,
                self.category,
                self.publisher,
                self.architecture,
                self.channel,
                self.name_startswith,
                self.featured,
            )
        )

    def find_kwargs(self) -> dict[str, Any]:
        """Keyword arguments accepted by ``StoreEndpoints.find()``."""
        values = {
            "confinement": self.confinement,
            "category": self.category,
            "publisher": self.publisher,
            "architecture": self.architecture,
            "channel": self.channel,
            "name_startswith": self.name_startswith,
            "featured": self.featured,
        }
        return {key: value for key, value in values.items() if value is not None}

    def summary(self) -> str:
        parts: list[str] = []
        if self.confinement:
            parts.append(self.confinement)
        if self.category:
            parts.append(self.category)
        if self.publisher:
            parts.append(f"by {self.publisher}")
        if self.architecture:
            parts.append(self.architecture)
        if self.channel:
            parts.append(self.channel)
        if self.name_startswith:
            parts.append(f"starts with {self.name_startswith}")
        if self.featured is not None:
            parts.append("featured" if self.featured else "not featured")
        return ", ".join(parts)


@dataclass(frozen=True)
class SearchRequest:
    query: str = ""
    filters: SearchFilters = field(default_factory=SearchFilters)

    @property
    def is_empty(self) -> bool:
        return not self.query.strip() and self.filters.is_empty


def rows_from_paginated_response(
    response: PaginatedSnapSearchResponse | None,
) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for item in response.results if response is not None else []:
        name = item.package_name or item.title
        if not name:
            continue
        rows.append(
            ResultRow(
                name=name,
                summary=item.summary or "",
                version=item.version or "",
            )
        )
    return rows


def rows_from_response(response: SearchResponse | None) -> list[ResultRow]:
    return rows_from_search_response(response)


def paginated_arch(filters: SearchFilters) -> str:
    return filters.architecture or "wide"


def paginated_confinement(filters: SearchFilters) -> str:
    return filters.confinement or "strict,classic"


__all__ = [
    "ArchSearchItem",
    "SearchFilters",
    "SearchRequest",
    "rows_from_paginated_response",
    "rows_from_response",
    "paginated_arch",
    "paginated_confinement",
]
