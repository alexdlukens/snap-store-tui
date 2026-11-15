"""InstalledScreen management actions with an independent fake client."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from snap_python.schemas.changes import ChangesResponse
from snap_python.schemas.snaps import InstalledSnap, InstalledSnapListResponse
from textual.app import App, ComposeResult
from textual.widgets import Button, DataTable, Header, OptionList, Static

from store_tui.screens.confirm import ConfirmScreen
from store_tui.screens.hold import HoldScreen
from store_tui.screens.installed import InstalledScreen
from store_tui.screens.logs import EMPTY_LOGS, LogsScreen


def snap(name: str = "alpha", **overrides) -> InstalledSnap:
    data = {
        "name": name,
        "summary": "Example snap",
        "version": "2.0.1",
        "revision": 42,
        "tracking-channel": "latest/stable",
        "confinement": "strict",
        "installed-size": 12_000_000,
        "install-date": "2026-01-02T03:04:05+00:00",
        "status": "active",
        "tracks": ["latest"],
        "components": [],
    }
    data.update(overrides)
    return InstalledSnap.model_validate(data)


def installed_list(snaps: list[InstalledSnap]) -> InstalledSnapListResponse:
    return InstalledSnapListResponse.model_validate(
        {
            "status-code": 200,
            "type": "sync",
            "status": "OK",
            "result": [item.model_dump(by_alias=True, mode="json") for item in snaps],
        }
    )


CHANGE = ChangesResponse.model_validate(
    {
        "status-code": 200,
        "type": "sync",
        "status": "OK",
        "result": {
            "id": "9",
            "kind": "refresh-snap",
            "summary": "Refresh snap",
            "status": "Done",
            "ready": True,
            "spawn-time": "2026-01-02T03:04:05+00:00",
            "ready-time": "2026-01-02T03:05:05+00:00",
            "tasks": [
                {
                    "id": "1",
                    "kind": "refresh",
                    "summary": "Refreshing alpha",
                    "status": "Done",
                    "progress": {"label": "refresh", "done": 1, "total": 1},
                    "spawn-time": "2026-01-02T03:04:05+00:00",
                }
            ],
        },
    }
)


class FakeChanges:
    def __init__(self) -> None:
        self.watch_ids: list[str] = []
        self.abort = AsyncMock(return_value=CHANGE)

    async def watch(self, change_id, timeout=None, poll_interval=0.5):
        self.watch_ids.append(str(change_id))
        yield CHANGE


class BlockingChanges(FakeChanges):
    """Watch that stays pending until abort() releases it."""

    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.released = asyncio.Event()
        self.abort_ids: list[str] = []
        self.abort = AsyncMock(side_effect=self._abort)

    async def watch(self, change_id, timeout=None, poll_interval=0.5):
        self.watch_ids.append(str(change_id))
        self.started.set()
        await self.released.wait()
        yield CHANGE

    async def _abort(self, change_id):
        self.abort_ids.append(change_id)
        self.released.set()
        return CHANGE


class FakeSnaps:
    def __init__(self, rows: list[InstalledSnap]) -> None:
        self.rows = rows
        self.list_installed_snaps = AsyncMock(side_effect=self._list)
        self.refresh_snap = AsyncMock(return_value=SimpleNamespace(change="9"))
        self.remove_snap = AsyncMock(return_value=SimpleNamespace(change="9"))
        self.hold_snap = AsyncMock(return_value=SimpleNamespace(change="9"))
        self.unhold_snap = AsyncMock(return_value=SimpleNamespace(change="9"))
        self.revert_snap = AsyncMock(return_value=SimpleNamespace(change="9"))
        self.disable_snap = AsyncMock(return_value=SimpleNamespace(change="9"))
        self.enable_snap = AsyncMock(return_value=SimpleNamespace(change="9"))

    async def _list(self, select=None):
        return installed_list(self.rows)


class FakeClient:
    def __init__(self, rows: list[InstalledSnap], changes=None) -> None:
        self.snaps = FakeSnaps(rows)
        self.changes = changes or FakeChanges()
        self.logs = SimpleNamespace(
            get_logs=AsyncMock(return_value=[]),
        )


class HostApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.errors: list[tuple[object, str]] = []

    def compose(self) -> ComposeResult:
        yield Static("host")

    def show_error(self, error: object, title: str) -> None:
        self.errors.append((error, title))


async def wait_until(pilot, predicate, attempts: int = 100) -> bool:
    for _ in range(attempts):
        if predicate():
            return True
        await pilot.pause()
    return predicate()


async def settle(pilot) -> None:
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


async def open_installed(pilot, client: FakeClient) -> InstalledScreen:
    screen = InstalledScreen(client=client)
    await pilot.app.push_screen(screen)
    await wait_until(
        pilot,
        lambda: client.snaps.list_installed_snaps.await_count >= 1,
    )
    await settle(pilot)
    return screen


@pytest.mark.asyncio
async def test_loads_rows_and_shows_details_for_highlighted_row() -> None:
    rows = [
        snap(
            "alpha",
            hold="2026-02-01T00:00:00+00:00",
            **{
                "refresh-inhibit": {"proceed-time": "2026-01-05T06:07:08+00:00"},
                "refresh-failures": {
                    "revision": 41,
                    "failure-count": 2,
                    "last-failure-time": "2026-01-03T04:05:06+00:00",
                    "last-failure-severity": "high",
                },
                "gating-hold": "2026-03-01T00:00:00+00:00",
                "broken": "",
                "components": [{"name": "gpu-support"}],
                "tracks": ["latest", "2.0"],
                "grade": "stable",
                "cohort-key": "cohort-7",
                "trymode": True,
            },
        ),
        snap("beta", status="disabled", confinement="classic"),
    ]
    client = FakeClient(rows)
    app = HostApp()

    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_installed(pilot, client)

        assert isinstance(screen.query_one(Header), Header)
        assert app.screen.title == "Installed snaps"
        assert screen.table.row_count == 2
        assert screen.table.get_row("alpha") == [
            "alpha",
            "2.0.1",
            "latest/stable",
            "42",
            "active",
        ]
        assert screen.empty_label.display is False
        assert screen.details.display is True

        details = str(screen.details.renderable)
        assert "Summary: Example snap" in details
        assert "12.0 MB" in details
        assert "Installed: 2026-01-02" in details
        assert "Hold: held until 2026-02-01" in details
        assert "Gating hold: 2026-03-01" in details
        assert "Refresh inhibit: 2026-01-05" in details
        assert "Refresh failures: 2 failed attempts" in details
        assert "last at 2026-01-03" in details
        assert "severity high" in details
        assert "Broken: no" in details
        assert "Tracks: latest, 2.0" in details
        assert "Components: gpu-support" in details
        assert "Confinement: strict" in details
        assert "Grade: stable" in details
        assert "Cohort: cohort-7" in details
        assert "Try mode: yes" in details

        screen.table.move_cursor(row=1)
        await pilot.pause()
        assert screen.selected_name == "beta"
        beta_details = str(screen.details.renderable)
        assert "Confinement: classic" in beta_details
        assert "Status: disabled" in beta_details


@pytest.mark.asyncio
async def test_empty_list_shows_empty_label() -> None:
    client = FakeClient([])
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_installed(pilot, client)

        assert screen.table.row_count == 0
        assert screen.table.display is False
        assert screen.empty_label.display is True
        assert screen.empty_label.renderable == "No snaps installed"
        assert str(screen.details.renderable) == ""


@pytest.mark.asyncio
async def test_refresh_watches_change_and_reloads() -> None:
    client = FakeClient([snap("alpha")])
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_installed(pilot, client)
        calls_before = client.snaps.list_installed_snaps.await_count

        await pilot.press("r")
        await settle(pilot)

        client.snaps.refresh_snap.assert_awaited_once_with(
            "alpha", channel=None, wait=False
        )
        assert client.changes.watch_ids == ["9"]
        assert client.snaps.list_installed_snaps.await_count == calls_before + 1
        assert str(screen.status_label.renderable) == "Refreshed alpha"
        assert screen.progress.display is False
        assert screen.cancel_button.display is False
        assert app.errors == []


@pytest.mark.asyncio
async def test_remove_requires_confirmation_and_purges() -> None:
    client = FakeClient([snap("alpha")])
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        await open_installed(pilot, client)

        await pilot.press("u")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        assert "purged" in app.screen.message
        assert "terminated" in app.screen.message

        await pilot.click("#confirm-confirm")
        await settle(pilot)

        client.snaps.remove_snap.assert_awaited_once_with(
            "alpha", purge=True, terminate=True, wait=False
        )
        assert client.changes.watch_ids == ["9"]


@pytest.mark.asyncio
async def test_remove_cancel_does_not_touch_snapd() -> None:
    client = FakeClient([snap("alpha")])
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        await open_installed(pilot, client)

        await pilot.press("u")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.press("escape")
        await pilot.pause()

        client.snaps.remove_snap.assert_not_awaited()


@pytest.mark.asyncio
async def test_hold_chooses_rfc3339_duration() -> None:
    client = FakeClient([snap("alpha")])
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        await open_installed(pilot, client)

        await pilot.press("h")
        assert await wait_until(pilot, lambda: isinstance(app.screen, HoldScreen))
        hold_screen = app.screen
        options = hold_screen.query_one(OptionList)
        assert options.option_count == 5
        options.highlighted = 1  # 7d
        await pilot.press("enter")
        await settle(pilot)

        args = client.snaps.hold_snap.await_args
        assert args.args[0] == "alpha"
        assert args.kwargs["hold_level"] == "general"
        assert args.kwargs["wait"] is False
        hold_time = args.kwargs["time"]
        parsed = datetime.fromisoformat(hold_time.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None
        assert abs((parsed - datetime.now(UTC)) - timedelta(days=7)) < timedelta(
            minutes=1
        )
        assert client.changes.watch_ids == ["9"]


@pytest.mark.asyncio
async def test_hold_forever_and_remove_hold() -> None:
    client = FakeClient([snap("alpha")])
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        await open_installed(pilot, client)

        await pilot.press("h")
        assert await wait_until(pilot, lambda: isinstance(app.screen, HoldScreen))
        options = app.screen.query_one(OptionList)
        options.highlighted = 3  # Forever
        await pilot.press("enter")
        await settle(pilot)
        assert client.snaps.hold_snap.await_args.kwargs["time"] == "forever"

        await pilot.press("h")
        assert await wait_until(pilot, lambda: isinstance(app.screen, HoldScreen))
        options = app.screen.query_one(OptionList)
        options.highlighted = 4  # Remove hold
        await pilot.press("enter")
        await settle(pilot)

        client.snaps.unhold_snap.assert_awaited_once_with("alpha", wait=False)


@pytest.mark.asyncio
async def test_revert_requires_confirmation() -> None:
    client = FakeClient([snap("alpha")])
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        await open_installed(pilot, client)

        await pilot.press("v")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        assert "previous revision" in app.screen.message
        await pilot.click("#confirm-confirm")
        await settle(pilot)

        client.snaps.revert_snap.assert_awaited_once_with("alpha", wait=False)


@pytest.mark.asyncio
async def test_disable_then_enable_uses_installed_status() -> None:
    client = FakeClient([snap("alpha")])
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_installed(pilot, client)

        await pilot.press("d")
        await settle(pilot)
        client.snaps.disable_snap.assert_awaited_once_with("alpha", wait=False)
        assert str(screen.status_label.renderable) == "Disabled alpha"

        client.snaps.rows = [snap("alpha", status="disabled")]
        await screen._load_rows()
        await pilot.pause()

        await pilot.press("d")
        await settle(pilot)
        client.snaps.enable_snap.assert_awaited_once_with("alpha", wait=False)
        assert str(screen.status_label.renderable) == "Enabled alpha"


@pytest.mark.asyncio
async def test_logs_screen_requests_service_logs_and_renders_lines() -> None:
    client = FakeClient([snap("alpha")])
    client.logs.get_logs.return_value = [
        SimpleNamespace(
            timestamp="2026-02-01T10:00:00.123456Z", message="service started"
        ),
        SimpleNamespace(timestamp="2026-02-01T10:00:01.000000Z", message="ready"),
    ]
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        await open_installed(pilot, client)

        await pilot.press("l")
        assert await wait_until(pilot, lambda: isinstance(app.screen, LogsScreen))
        logs = app.screen
        await settle(pilot)

        client.logs.get_logs.assert_awaited_once_with(names=["alpha"], n=200)
        text = str(logs.content.renderable)
        assert "2026-02-01T10:00:00.123456Z" in text
        assert "service started" in text
        assert "ready" in text


@pytest.mark.asyncio
async def test_logs_screen_shows_empty_message() -> None:
    client = FakeClient([snap("alpha")])
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        await open_installed(pilot, client)

        await pilot.press("l")
        assert await wait_until(pilot, lambda: isinstance(app.screen, LogsScreen))
        logs = app.screen
        await settle(pilot)

        assert str(logs.content.renderable) == EMPTY_LOGS


@pytest.mark.asyncio
async def test_cancel_aborts_watched_change_without_error_screen() -> None:
    changes = BlockingChanges()
    client = FakeClient([snap("alpha")], changes=changes)
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_installed(pilot, client)

        await pilot.press("r")
        assert await wait_until(pilot, changes.started.is_set)
        assert await wait_until(pilot, lambda: screen.cancel_button.display is True)

        await pilot.click("#installed-cancel")
        assert await wait_until(pilot, lambda: changes.abort_ids == ["9"])
        assert await wait_until(
            pilot, lambda: str(screen.status_label.renderable) == "Change cancelled"
        )

        assert changes.abort_ids == ["9"]
        assert screen.cancel_button.display is False
        assert screen._change_running is False
        assert app.errors == []


@pytest.mark.asyncio
async def test_failure_uses_show_error() -> None:
    client = FakeClient([snap("alpha")])
    client.snaps.refresh_snap.side_effect = RuntimeError("snapd is offline")
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_installed(pilot, client)

        await pilot.press("r")
        await settle(pilot)

        assert len(app.errors) == 1
        error, title = app.errors[0]
        assert "snapd is offline" in str(error)
        assert title == "Error - refresh snap"
        assert str(screen.status_label.renderable) == "Operation failed"


@pytest.mark.asyncio
async def test_cancel_only_visible_during_operation() -> None:
    client = FakeClient([snap("alpha")])
    app = HostApp()

    async with app.run_test(size=(100, 30)) as pilot:
        screen = await open_installed(pilot, client)

        assert screen.cancel_button.display is False
        assert screen.progress.display is False
        assert isinstance(screen.query_one("#installed-refresh", Button), Button)
        assert isinstance(screen.query_one("#installed-remove", Button), Button)
        assert isinstance(screen.query_one(DataTable), DataTable)
        assert isinstance(screen.query_one("#installed-details", Static), Static)
