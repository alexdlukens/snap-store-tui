"""Search request models and row conversion."""

from __future__ import annotations

import pytest
from snap_python.schemas.store.search import (
    PaginatedSnapSearchResponse,
    SearchResponse,
)

from store_tui.search import (
    SearchFilters,
    rows_from_paginated_response,
    rows_from_response,
)


def test_find_kwargs_omits_unset_values() -> None:
    assert SearchFilters().find_kwargs() == {}

    filters = SearchFilters(
        confinement="strict",
        category="games",
        publisher="Canonical",
        architecture="amd64",
        channel="edge",
        name_startswith="snap",
        featured=True,
    )
    assert filters.find_kwargs() == {
        "confinement": "strict",
        "category": "games",
        "publisher": "Canonical",
        "architecture": "amd64",
        "channel": "edge",
        "name_startswith": "snap",
        "featured": True,
    }


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        (SearchFilters(), False),
        (SearchFilters(confinement="strict", architecture="amd64"), False),
        (SearchFilters(category="games"), True),
        (SearchFilters(publisher="Canonical"), True),
        (SearchFilters(channel="edge"), True),
        (SearchFilters(name_startswith="vlc"), True),
        (SearchFilters(featured=True), True),
        (SearchFilters(featured=False), True),
    ],
)
def test_advanced_needs_full_find(filters: SearchFilters, expected: bool) -> None:
    assert filters.advanced is expected


def test_summary_lists_every_filter() -> None:
    assert SearchFilters().summary() == ""
    filters = SearchFilters(
        confinement="strict",
        category="games",
        publisher="Canonical",
        architecture="amd64",
        channel="edge",
        name_startswith="snap",
        featured=True,
    )
    assert filters.summary() == (
        "strict, games, by Canonical, amd64, edge, starts with snap, featured"
    )
    assert SearchFilters(featured=False).summary() == "not featured"


def test_rows_from_paginated_response_prefers_package_name() -> None:
    response = PaginatedSnapSearchResponse.model_validate(
        {
            "total": 3,
            "page": 1,
            "limit": 10,
            "results": [
                {
                    "package_name": "vlc",
                    "title": "VLC media player",
                    "summary": "Play media",
                    "version": "3.0.20",
                    "aliases": [],
                    "apps": [],
                },
                {
                    "package_name": "",
                    "title": "Firefox",
                    "summary": "Browse the web",
                    "version": "128.0",
                    "aliases": [],
                    "apps": [],
                },
                {
                    "package_name": "",
                    "title": "",
                    "summary": "No name",
                    "version": "1.0",
                    "aliases": [],
                    "apps": [],
                },
            ],
        }
    )
    rows = rows_from_paginated_response(response)
    assert [(row.name, row.summary, row.version) for row in rows] == [
        ("vlc", "Play media", "3.0.20"),
        ("Firefox", "Browse the web", "128.0"),
    ]
    assert rows_from_paginated_response(None) == []


def test_rows_from_response_includes_revision_version() -> None:
    response = SearchResponse.model_validate(
        {
            "results": [
                {
                    "name": "vlc",
                    "snap-id": "abcdef",
                    "snap": {"name": "vlc", "summary": "Play media"},
                    "revision": {
                        "revision": 3078,
                        "version": "3.0.20",
                        "channel": "stable",
                        "confinement": "strict",
                    },
                }
            ]
        }
    )
    rows = rows_from_response(response)
    assert [(row.name, row.summary, row.version) for row in rows] == [
        ("vlc", "Play media", "3.0.20")
    ]
    assert rows_from_response(None) == []
