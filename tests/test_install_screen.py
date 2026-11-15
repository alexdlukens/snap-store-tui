"""Install screen behaviour for install, update, switch, revert, and cancel."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from snap_python.schemas.changes import ChangesResponse
from snap_python.schemas.snaps import InstalledSnap
from snap_python.schemas.store.info import InfoResponse
from textual.app import App, ComposeResult
from textual.widgets import Static

from store_tui.channels import MODES, channel_label
from store_tui.screens.confirm import ConfirmScreen
from store_tui.screens.error import ErrorScreen
from store_tui.screens.install import InstallScreen
from store_tui.snapd import InstalledState
from tests.support import SNAP_INFO_MULTI_TRACK

SNAP_NAME = "demo"
CHANNEL = "latest/stable"
CHANGE_ID = "42"


def _channel(name: str) -> dict:
    return {
        "architecture": "amd64",
        "name": name,
        "risk": name,
        "track": "latest",
        "released-at": "2025-01-02T03:04:05+00:00",
    }


def demo_info(channels: list[dict] | None = None) -> InfoResponse:
    channel_map = (
        [{"channel": _channel("stable")}, {"channel": _channel("edge")}]
        if channels is None
        else channels
    )
    return InfoResponse.model_validate(
        {
            "channel-map": channel_map,
            "name": SNAP_NAME,
            "snap": {
                "name": SNAP_NAME,
                "title": "Demo",
                "summary": "A demo snap",
                "description": "Demo description",
                "license": "MIT",
                "store-url": "https://snapcraft.io/demo",
            },
            "snap-id": "demo-id",
        }
    )


def installed_snap(channel: str = CHANNEL) -> InstalledSnap:
    return InstalledSnap.model_validate(
        {
            "name": SNAP_NAME,
            "summary": "A demo snap",
            "version": "1.0",
            "revision": 7,
            "tracking-channel": channel,
            "confinement": "strict",
            "installed-size": 1_000_000,
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
    )


def change(*, ready: bool = True, err: str | None = None) -> ChangesResponse:
    result: dict = {
        "id": CHANGE_ID,
        "kind": "install-snap",
        "summary": "Install demo",
        "status": "Done" if ready else "Doing",
        "ready": ready,
        "spawn-time": "2026-01-02T03:04:05+00:00",
        "tasks": [
            {
                "id": "1",
                "kind": "task",
                "summary": "Install demo",
                "status": "Done" if ready else "Doing",
                "progress": {"label": "task", "done": 1, "total": 1},
                "spawn-time": "2026-01-02T03:04:05+00:00",
            }
        ],
    }
    if ready:
        result["ready-time"] = "2026-01-02T03:05:05+00:00"
    if err is not None:
        result["err"] = err
    return ChangesResponse.model_validate(
        {
            "status-code": 200,
            "type": "sync",
            "status": "OK",
            "result": result,
        }
    )


class FakeChanges:
    def __init__(self) -> None:
        self.results = [change()]
        self.watch_error: Exception | None = None
        self.gate: asyncio.Event | None = None
        self.abort = AsyncMock(return_value=change())
        self.watch_calls: list[str] = []

    def watch(self, change_id, timeout=None, poll_interval=0.5):
        self.watch_calls.append(change_id)
        return self._watch()

    async def _watch(self):
        if self.gate is not None:
            await self.gate.wait()
        if self.watch_error is not None:
            raise self.watch_error
        for item in self.results:
            yield item


class FakeClient:
    def __init__(self, installed: InstalledSnap | None = None) -> None:
        self.snaps = SimpleNamespace(
            get_installed_snap=AsyncMock(return_value=installed),
            install_snap=AsyncMock(return_value=SimpleNamespace(change=CHANGE_ID)),
            refresh_snap=AsyncMock(return_value=SimpleNamespace(change=CHANGE_ID)),
            switch_channel=AsyncMock(return_value=SimpleNamespace(change=CHANGE_ID)),
            revert_snap=AsyncMock(return_value=SimpleNamespace(change=CHANGE_ID)),
            remove_snap=AsyncMock(return_value=SimpleNamespace(change=CHANGE_ID)),
        )
        self.changes = FakeChanges()


class HostApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Static("host")

    def show_error(self, error: BaseException | str | object, title: str) -> None:
        self.push_screen(ErrorScreen(error, title))


async def settle(app: HostApp, pilot) -> None:
    await app.workers.wait_for_complete()
    await pilot.pause()


async def wait_until(pilot, predicate, attempts: int = 100) -> bool:
    for _ in range(attempts):
        if predicate():
            return True
        await pilot.pause()
    return predicate()


async def open_screen(
    pilot,
    client: FakeClient,
    install_state: InstalledState,
    info: InfoResponse | None = None,
) -> InstallScreen:
    screen = InstallScreen(
        snap_info=info or demo_info(),
        install_state=install_state,
        client=client,
    )
    await pilot.app.push_screen(screen)
    await settle(pilot.app, pilot)
    return screen


async def select_item(pilot, list_view, name: str) -> None:
    names = [str(item.name) for item in list_view.children]
    assert name in names, f"{name} not in {names}"
    list_view.index = names.index(name)
    await pilot.pause()
    await pilot.pause()


async def test_track_and_risk_selection_updates_channel(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client = FakeClient()
    app = HostApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_screen(
            pilot,
            client,
            InstalledState(installed=False),
            info=SNAP_INFO_MULTI_TRACK,
        )

        await select_item(pilot, screen.track_list, "2.0")
        assert screen.selected_track == "2.0"
        assert screen.selected_risk == "stable"
        assert channel_label(screen.selected_channel) == "2.0/stable"

        await select_item(pilot, screen.risk_list, "beta")
        assert screen.selected_track == "2.0"
        assert screen.selected_risk == "beta"
        assert channel_label(screen.selected_channel) == "2.0/beta"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("strict", {"classic": False, "devmode": False, "jailmode": False}),
        ("classic", {"classic": True, "devmode": False, "jailmode": False}),
        ("devmode", {"classic": False, "devmode": True, "jailmode": False}),
        ("jailmode", {"classic": False, "devmode": False, "jailmode": True}),
    ],
)
async def test_not_installed_installs_selected_channel_and_mode(
    monkeypatch, mode: str, expected: dict[str, bool]
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client = FakeClient()
    app = HostApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_screen(pilot, client, InstalledState(installed=False))

        screen.mode_list.index = MODES.index(mode)
        await pilot.pause()
        assert screen.mode == mode

        await pilot.click("#install-button")
        assert await wait_until(
            pilot,
            lambda: client.snaps.install_snap.await_count == 1
            and not screen._change_running,
        )
        await settle(app, pilot)

        kwargs = client.snaps.install_snap.await_args.kwargs
        assert kwargs["snap"] == SNAP_NAME
        assert kwargs["channel"] == "latest/stable"
        assert kwargs["classic"] is expected["classic"]
        assert kwargs["devmode"] is expected["devmode"]
        assert kwargs["jailmode"] is expected["jailmode"]
        assert kwargs["dangerous"] is False
        assert kwargs["wait"] is False
        assert (
            str(screen.status_label.renderable) == "Installed demo from latest/stable"
        )


@pytest.mark.parametrize("size", [(80, 24), (120, 40)])
async def test_layout_regions_fit_inside_screen(monkeypatch, size) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    width, height = size
    client = FakeClient()
    app = HostApp()
    async with app.run_test(size=size) as pilot:
        screen = await open_screen(
            pilot,
            client,
            InstalledState(installed=False),
            info=SNAP_INFO_MULTI_TRACK,
        )

        selectors = [
            "#install-header",
            "#install-tracks",
            "#install-risks",
            "#install-side",
            "#track-list",
            "#risk-list",
            "#mode-list",
            "#install-actions",
            "#install-button",
            "#uninstall-button",
            "#revert-button",
        ]
        for selector in selectors:
            region = screen.query_one(selector).region
            assert region.width > 0, selector
            assert region.height > 0, selector
            assert region.x >= 0, selector
            assert region.y >= 0, selector
            assert region.right <= width, selector
            assert region.bottom <= height, selector

        assert screen.cancel_button.display is False


async def test_installed_on_selected_channel_updates(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client = FakeClient(installed_snap(CHANNEL))
    app = HostApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_screen(
            pilot,
            client,
            InstalledState(installed=True, channel=CHANNEL, version="1.0"),
        )

        assert str(screen.install_button.label) == "Update from latest/stable"
        assert screen.install_button.disabled is False

        await pilot.click("#install-button")
        assert await wait_until(
            pilot,
            lambda: client.snaps.refresh_snap.await_count == 1
            and not screen._change_running,
        )
        await settle(app, pilot)

        assert client.snaps.refresh_snap.await_args.args[0] == SNAP_NAME
        assert client.snaps.refresh_snap.await_args.kwargs["channel"] is None
        assert client.snaps.refresh_snap.await_args.kwargs["wait"] is False
        assert client.snaps.install_snap.await_count == 0
        assert str(screen.status_label.renderable) == "Updated demo from latest/stable"


async def test_installed_on_other_channel_switches(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client = FakeClient(installed_snap("latest/beta"))
    app = HostApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_screen(
            pilot,
            client,
            InstalledState(installed=True, channel="latest/beta", version="1.0"),
        )

        assert str(screen.install_button.label) == "Switch to latest/stable"
        assert screen.install_button.disabled is False

        await pilot.click("#install-button")
        assert await wait_until(
            pilot,
            lambda: client.snaps.switch_channel.await_count == 1
            and not screen._change_running,
        )
        await settle(app, pilot)

        assert client.snaps.switch_channel.await_args.args[0] == SNAP_NAME
        assert (
            client.snaps.switch_channel.await_args.kwargs["channel"] == "latest/stable"
        )
        assert client.snaps.switch_channel.await_args.kwargs["wait"] is False
        assert str(screen.status_label.renderable) == "Switched demo to latest/stable"


async def test_cancel_aborts_change_without_error_screen(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client = FakeClient()
    gate = asyncio.Event()
    client.changes.gate = gate
    client.changes.watch_error = RuntimeError("change aborted")
    app = HostApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_screen(pilot, client, InstalledState(installed=False))
        assert screen.cancel_button.display is False

        await pilot.click("#install-button")
        assert await wait_until(pilot, lambda: screen._change_id == CHANGE_ID)
        assert screen.cancel_button.display is True

        await pilot.click("#cancel-button")
        assert await wait_until(pilot, lambda: client.changes.abort.await_count == 1)
        client.changes.abort.assert_awaited_once_with(CHANGE_ID)
        assert str(screen.status_label.renderable) == "Cancelling…"
        assert not isinstance(app.screen, ErrorScreen)

        gate.set()
        assert await wait_until(pilot, lambda: not screen._change_running)
        await settle(app, pilot)

        assert not isinstance(app.screen, ErrorScreen)
        assert str(screen.status_label.renderable) == "Operation cancelled"
        assert screen.cancel_button.display is False


async def test_revert_confirmation_reverts_snap(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client = FakeClient(installed_snap(CHANNEL))
    app = HostApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_screen(
            pilot, client, InstalledState(installed=True, channel=CHANNEL)
        )

        assert screen.revert_button.disabled is False
        await pilot.press("r")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        assert await wait_until(
            pilot,
            lambda: str(app.screen.query_one("#confirm-title").renderable)
            == "Revert snap?",
        )

        await pilot.click("#confirm-confirm")
        assert await wait_until(
            pilot,
            lambda: client.snaps.revert_snap.await_count == 1
            and not screen._change_running,
        )
        await settle(app, pilot)

        assert client.snaps.revert_snap.await_args.args[0] == SNAP_NAME
        assert client.snaps.revert_snap.await_args.kwargs["wait"] is False
        assert str(screen.status_label.renderable) == "Reverted demo"


async def test_uninstall_confirmation_removes_snap_with_data(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client = FakeClient(installed_snap(CHANNEL))
    app = HostApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_screen(
            pilot, client, InstalledState(installed=True, channel=CHANNEL)
        )

        await pilot.click("#uninstall-button")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.click("#confirm-confirm")
        assert await wait_until(
            pilot,
            lambda: client.snaps.remove_snap.await_count == 1
            and not screen._change_running,
        )
        await settle(app, pilot)

        assert client.snaps.remove_snap.await_args.args[0] == SNAP_NAME
        assert client.snaps.remove_snap.await_args.kwargs == {
            "purge": True,
            "terminate": True,
            "wait": False,
        }
        assert str(screen.status_label.renderable) == "Removed demo and its data"


async def test_escape_and_q_are_ignored_while_change_runs(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client = FakeClient()
    gate = asyncio.Event()
    client.changes.gate = gate
    app = HostApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_screen(pilot, client, InstalledState(installed=False))

        await pilot.click("#install-button")
        assert await wait_until(pilot, lambda: screen._change_id == CHANGE_ID)

        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is screen
        assert screen._change_running is True

        await pilot.press("q")
        await pilot.pause()
        assert app.screen is screen
        assert screen._change_running is True
        assert "Operation in progress" in str(screen.status_label.renderable)

        gate.set()
        assert await wait_until(pilot, lambda: not screen._change_running)
        await settle(app, pilot)


async def test_watch_failure_opens_error_screen(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client = FakeClient()
    client.changes.watch_error = RuntimeError("snapd exploded")
    app = HostApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_screen(pilot, client, InstalledState(installed=False))

        await pilot.click("#install-button")
        assert await wait_until(pilot, lambda: not screen._change_running)
        await settle(app, pilot)

        assert isinstance(app.screen, ErrorScreen)
        assert "snapd exploded" in app.screen.error_text
        assert str(screen.status_label.renderable) == "Operation failed"


async def test_no_channels_keeps_installed_actions_enabled(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client = FakeClient(installed_snap(CHANNEL))
    app = HostApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = await open_screen(
            pilot,
            client,
            InstalledState(installed=True, channel=CHANNEL),
            info=demo_info(channels=[]),
        )

        assert screen.channels == []
        assert screen.install_button.disabled is True
        assert screen.uninstall_button.disabled is False
        assert screen.revert_button.disabled is False

        await pilot.click("#uninstall-button")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
