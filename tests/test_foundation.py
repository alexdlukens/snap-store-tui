"""Foundation tests for the typed snapd adapter and shared helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from snap_python.utils import SnapdAPIError

from store_tui.changes import progress_of, watch_change
from store_tui.client import client_available, close_client
from store_tui.errors import error_text_with_hint, snapd_error_hint
from store_tui.screens.error import format_error
from store_tui.snapd import (
    InstalledState,
    SnapdError,
    get_installed_state,
    list_installed,
    list_revisions,
    row_from_installed,
    state_from_installed,
)
from tests.support import installed_list, installed_snap


def test_row_from_installed_exposes_management_fields() -> None:
    snap = installed_snap(
        hold="2026-02-01T00:00:00+00:00",
        gating_hold="2026-03-01T00:00:00+00:00",
        refresh_inhibit={"proceed-time": "2026-04-01T00:00:00+00:00"},
        refresh_failures={
            "failure-count": 2,
            "last-failure-time": "2026-01-03T00:00:00+00:00",
        },
        broken="revision is broken",
        trymode=True,
        devmode=True,
        cohort_key="cohort",
        grade="stable",
        tracks=["latest", "2.0"],
        components=[{"name": "core", "version": "1.0"}],
    )

    row = row_from_installed(snap)

    assert row.name == "py-rand-tool"
    assert row.version == "1.2.3"
    assert row.revision == 7
    assert row.channel == "latest/stable"
    assert row.confinement == "strict"
    assert row.size == 12_000_000
    assert row.install_date is not None
    assert row.hold is not None
    assert row.gating_hold is not None
    assert row.refresh_inhibit is not None
    assert row.broken == "revision is broken"
    assert row.trymode is True
    assert row.devmode is True
    assert row.status == "active"
    assert row.grade == "stable"
    assert row.cohort_key == "cohort"
    assert row.tracks == ("latest", "2.0")
    assert row.components == ("core",)
    assert row.refresh_failures.failure_count == 2


def test_state_from_installed_and_missing() -> None:
    state = state_from_installed(installed_snap())
    assert state.installed is True
    assert state.version == "1.2.3"
    assert state.channel == "latest/stable"

    missing = state_from_installed(None)
    assert missing == InstalledState(installed=False)


async def test_get_installed_state_handles_404_and_errors() -> None:
    client = SimpleNamespace(
        snaps=SimpleNamespace(get_installed_snap=AsyncMock(return_value=None))
    )
    state = await get_installed_state(client, "missing")
    assert state.installed is False
    assert state.error is None

    client.snaps.get_installed_snap = AsyncMock(
        side_effect=SnapdAPIError("boom", kind="snap-not-found")
    )
    state = await get_installed_state(client, "missing")
    assert state.installed is False
    assert state.error is not None

    client.snaps.get_installed_snap = AsyncMock(return_value=installed_snap())
    state = await get_installed_state(client, "py-rand-tool")
    assert state.installed is True
    assert state.version == "1.2.3"


async def test_list_installed_uses_typed_endpoint_and_sorts() -> None:
    client = SimpleNamespace(
        snaps=SimpleNamespace(
            list_installed_snaps=AsyncMock(
                return_value=installed_list(
                    [installed_snap("zeta"), installed_snap("alpha")]
                )
            )
        )
    )

    rows = await list_installed(client, select="all")

    client.snaps.list_installed_snaps.assert_awaited_once_with(select="all")
    assert [row.name for row in rows] == ["alpha", "zeta"]


async def test_list_installed_wraps_failures() -> None:
    client = SimpleNamespace(
        snaps=SimpleNamespace(
            list_installed_snaps=AsyncMock(side_effect=RuntimeError("snapd exploded"))
        )
    )
    with pytest.raises(SnapdError, match="snapd exploded"):
        await list_installed(client)


async def test_list_revisions_requests_all_and_sorts_newest_first() -> None:
    client = SimpleNamespace(
        snaps=SimpleNamespace(
            list_installed_snaps=AsyncMock(
                return_value=installed_list(
                    [
                        installed_snap("foo", revision=1),
                        installed_snap("foo", revision=10),
                        installed_snap("foo", revision=5),
                    ]
                )
            )
        )
    )

    rows = await list_revisions(client, "foo")

    client.snaps.list_installed_snaps.assert_awaited_once_with(
        select="all", snaps=["foo"]
    )
    assert [row.revision for row in rows] == [10, 5, 1]


async def test_client_available_prefers_is_available() -> None:
    client = SimpleNamespace(is_available=AsyncMock(return_value=True))
    assert await client_available(client) is True

    client.is_available = AsyncMock(return_value=False)
    assert await client_available(client) is False

    client.is_available = AsyncMock(side_effect=RuntimeError("down"))
    assert await client_available(client) is False


async def test_client_available_falls_back_to_ping() -> None:
    client = SimpleNamespace(
        ping=AsyncMock(return_value=SimpleNamespace(status_code=200))
    )
    assert await client_available(client) is True

    client.ping = AsyncMock(return_value=SimpleNamespace(status_code=503))
    assert await client_available(client) is False


async def test_close_client_prefers_close() -> None:
    client = SimpleNamespace(close=AsyncMock())
    await close_client(client)
    client.close.assert_awaited_once()


async def test_watch_change_returns_ready_and_progress() -> None:
    from tests.support import IN_PROGRESS_CHANGE, READY_CHANGE

    class FakeChanges:
        async def watch(self, change_id, timeout=None, poll_interval=0.5):
            yield IN_PROGRESS_CHANGE
            yield READY_CHANGE

    client = SimpleNamespace(changes=FakeChanges())
    seen = []
    ready = await watch_change(client, "1", on_change=seen.append)

    assert ready is READY_CHANGE
    assert [change.ready for change in seen] == [False, True]
    done, total, message = progress_of(IN_PROGRESS_CHANGE)
    assert (done, total) == (1, 2)
    assert message == "Install snap"


async def test_watch_change_rejects_empty_stream() -> None:
    class FakeChanges:
        async def watch(self, change_id, timeout=None, poll_interval=0.5):
            if False:  # pragma: no cover
                yield None

    with pytest.raises(RuntimeError, match="change stream ended"):
        await watch_change(SimpleNamespace(changes=FakeChanges()), "1")


def test_error_hints_and_error_screen_prefix() -> None:
    conflict = SnapdAPIError("busy", kind="snap-change-conflict")
    assert "Another snap operation" in (snapd_error_hint(conflict) or "")
    assert "Another snap operation" in error_text_with_hint(conflict)
    assert "Another snap operation" in format_error(conflict)

    assert snapd_error_hint(SnapdAPIError("no")) is None
    unauthorized = SnapdAPIError("denied", status_code=403)
    assert "Permission denied" in (snapd_error_hint(unauthorized) or "")
