"""Shared 0.2.0 fake client and validated fixtures for the test suite."""

from __future__ import annotations

import pathlib
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from snap_python.schemas.changes import ChangesListResponse, ChangesResponse
from snap_python.schemas.snaps import InstalledSnap, InstalledSnapListResponse
from snap_python.schemas.store.categories import CategoryResponse
from snap_python.schemas.store.info import InfoResponse
from snap_python.schemas.store.search import (
    PaginatedSnapSearchResponse,
    SearchResponse,
)

DATA_DIR = pathlib.Path(__file__).parent / "data"


def load(name: str, model):
    return model.model_validate_json((DATA_DIR / name).read_text())


CATEGORIES = load("categories_response.json", CategoryResponse)
FEATURED = load("featured_snaps_response.json", SearchResponse)
SNAP_INFO = load("snap_info_response_success.json", InfoResponse)
SNAP_INFO_NO_CHANNELS = load("snap_info_response_no_channels.json", InfoResponse)
SNAP_INFO_MULTI_TRACK = load("snap_info_response_multi_track.json", InfoResponse)


def installed_snap(name: str = "py-rand-tool", **overrides: Any) -> InstalledSnap:
    data: dict[str, Any] = {
        "name": name,
        "summary": "CLI tool",
        "version": "1.2.3",
        "revision": 7,
        "tracking-channel": "latest/stable",
        "confinement": "strict",
        "installed-size": 12_000_000,
        "install-date": "2026-01-02T03:04:05+00:00",
        "status": "active",
        "tracks": ["latest"],
        "channels": {},
        "components": [],
        "devmode": False,
        "jailmode": False,
        "trymode": False,
        "grade": "stable",
    }
    data.update(overrides)
    return InstalledSnap.model_validate(data)


def installed_list(snaps: list[InstalledSnap]) -> InstalledSnapListResponse:
    return InstalledSnapListResponse.model_validate(
        {
            "status-code": 200,
            "type": "sync",
            "status": "OK",
            "result": [snap.model_dump(by_alias=True, mode="json") for snap in snaps],
        }
    )


def change(
    change_id: str = "1",
    *,
    summary: str = "Install snap",
    kind: str = "install-snap",
    status: str = "Doing",
    ready: bool = False,
    done: int = 1,
    total: int = 2,
    err: str | None = None,
) -> ChangesResponse:
    result: dict[str, Any] = {
        "id": change_id,
        "kind": kind,
        "summary": summary,
        "status": status,
        "ready": ready,
        "spawn-time": "2026-01-02T03:04:05+00:00",
        "tasks": [
            {
                "id": "1",
                "kind": "task",
                "summary": summary,
                "status": "Doing" if not ready else "Done",
                "progress": {"label": "task", "done": done, "total": total},
                "spawn-time": "2026-01-02T03:04:05+00:00",
            }
        ],
    }
    if ready:
        result["ready-time"] = "2026-01-02T03:05:05+00:00"
    if err:
        result["err"] = err
    return ChangesResponse.model_validate(
        {
            "status-code": 200,
            "type": "sync",
            "status": "OK",
            "result": result,
        }
    )


READY_CHANGE = change(ready=True, status="Done", done=2)
IN_PROGRESS_CHANGE = change()


def changes_list(changes: list[ChangesResponse]) -> ChangesListResponse:
    return ChangesListResponse.model_validate(
        {
            "status-code": 200,
            "type": "sync",
            "status": "OK",
            "result": [
                c.result.model_dump(by_alias=True, mode="json")
                for c in changes
                if not isinstance(c.result, dict)
            ],
        }
    )


def paginated(
    names: list[str], *, page: int = 1, limit: int = 100, total: int | None = None
) -> PaginatedSnapSearchResponse:
    total = len(names) if total is None else total
    return PaginatedSnapSearchResponse.model_validate(
        {
            "total": total,
            "page": page,
            "limit": limit,
            "results": [
                {
                    "package_name": name,
                    "title": name.title(),
                    "summary": f"{name} summary",
                    "version": "1.0",
                    "apps": [],
                    "aliases": [],
                }
                for name in names
            ],
        }
    )


class FakeChanges:
    def __init__(self) -> None:
        self.watch_changes: list[ChangesResponse] = [READY_CHANGE]
        self.list_changes = AsyncMock(return_value=changes_list([READY_CHANGE]))
        self.abort = AsyncMock(return_value=change(ready=True, status="Done"))

    def watch(self, change_id, timeout=None, poll_interval=0.5):
        async def stream():
            for item in self.watch_changes:
                yield item

        return stream()


class FakeClient:
    """Minimal SnapClient stand-in exposing only what the UI uses."""

    def __init__(self) -> None:
        self.store = SimpleNamespace(
            get_categories=AsyncMock(return_value=CATEGORIES),
            find=AsyncMock(return_value=FEATURED),
            retry_get_snap_info=AsyncMock(return_value=SNAP_INFO),
            get_snap_search_paginated=AsyncMock(
                return_value=paginated([result.name for result in FEATURED.results])
            ),
            get_top_snaps_from_category=AsyncMock(return_value=FEATURED),
        )
        self.snaps = SimpleNamespace(
            get_installed_snap=AsyncMock(return_value=None),
            list_installed_snaps=AsyncMock(return_value=installed_list([])),
            install_snap=AsyncMock(return_value=SimpleNamespace(change="1")),
            refresh_snap=AsyncMock(return_value=SimpleNamespace(change="1")),
            switch_channel=AsyncMock(return_value=SimpleNamespace(change="1")),
            revert_snap=AsyncMock(return_value=SimpleNamespace(change="1")),
            remove_snap=AsyncMock(return_value=SimpleNamespace(change="1")),
            disable_snap=AsyncMock(return_value=SimpleNamespace(change="1")),
            enable_snap=AsyncMock(return_value=SimpleNamespace(change="1")),
            hold_snap=AsyncMock(return_value=SimpleNamespace(change="1")),
            unhold_snap=AsyncMock(return_value=SimpleNamespace(change="1")),
            list_apps=AsyncMock(return_value=SimpleNamespace(result=[])),
        )
        self.changes = FakeChanges()
        self.logs = SimpleNamespace(
            get_logs=AsyncMock(return_value=[]),
        )
        self.is_available = AsyncMock(return_value=True)
        self.close = AsyncMock()


def with_snap_info(info: InfoResponse, **changes: Any) -> InfoResponse:
    data = deepcopy(info.model_dump(by_alias=True, mode="json"))
    data.update(changes)
    return InfoResponse.model_validate(data)
