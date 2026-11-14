"""Deterministic UI tests for the Snap Store TUI.

All network access is replaced by a lightweight fake client; fixtures live in
``tests/data`` and are parsed once at import time.
"""

from __future__ import annotations

import asyncio
import pathlib
import subprocess
import sys
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import humanize
import pytest
from snap_python.schemas.changes import ChangesResponse
from snap_python.schemas.store.categories import CategoryResponse
from snap_python.schemas.store.info import InfoResponse
from snap_python.schemas.store.search import SearchResponse
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import (
    DataTable,
    Footer,
    Label,
    Markdown,
    OptionList,
    ProgressBar,
)

from store_tui.app import BrowseMode, StoreApp
from store_tui.client import close_client, create_client
from store_tui.screens.category import CategoryScreen
from store_tui.screens.confirm import ConfirmScreen
from store_tui.screens.error import ErrorScreen
from store_tui.screens.install import InstallScreen
from store_tui.screens.search import SearchScreen
from store_tui.screens.snap import SnapScreen
from store_tui.snapd import (
    InstalledState,
    SnapdError,
    get_installed_state,
    list_installed,
)
from store_tui.widgets.clickable_link import ClickableLink
from store_tui.widgets.progress import ProgressBarWithMessage
from store_tui.widgets.results_table import ResultRow

DATA_DIR = pathlib.Path(__file__).parent / "data"
REPO_ROOT = pathlib.Path(__file__).parent.parent
TERMINAL_SIZE = (120, 40)


def _load(name: str, model):
    return model.model_validate_json((DATA_DIR / name).read_text())


CATEGORIES = _load("categories_response.json", CategoryResponse)
FEATURED = _load("featured_snaps_response.json", SearchResponse)
SNAP_INFO = _load("snap_info_response_success.json", InfoResponse)
SNAP_INFO_NO_CHANNELS = _load("snap_info_response_no_channels.json", InfoResponse)
SNAP_INFO_MULTI_TRACK = _load("snap_info_response_multi_track.json", InfoResponse)


def _response(payload, status_code: int = 200):
    return SimpleNamespace(status_code=status_code, json=lambda: payload)


def _http_error(status_code: int, endpoint: str) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", f"http://localhost/v2/{endpoint}")
    response = httpx.Response(status_code, request=request)
    return httpx.HTTPStatusError("request failed", request=request, response=response)


ERROR_CHANGE = ChangesResponse.model_validate(
    {
        "status-code": 200,
        "type": "error",
        "status": "Error",
        "result": {"message": "cannot install snap"},
    }
)


class FakeClient:
    """Stand-in for SnapClient exposing pysnap's public request() surface."""

    def __init__(self, *, snap_info: InfoResponse = SNAP_INFO) -> None:
        self.store = SimpleNamespace(
            get_categories=AsyncMock(return_value=CATEGORIES),
            get_top_snaps_from_category=AsyncMock(return_value=FEATURED),
            find=AsyncMock(return_value=FEATURED),
            retry_get_snap_info=AsyncMock(return_value=snap_info),
        )
        self.snaps = SimpleNamespace(
            install_snap=AsyncMock(side_effect=self._install),
            remove_snap=AsyncMock(side_effect=self._remove),
        )
        self.ping = AsyncMock(return_value=SimpleNamespace(status_code=200))
        self.changes: list[ChangesResponse] = []
        self.loop_changes = True
        self.installed_names: set[str] = set()
        self.requests: list[str] = []
        self.installed_list_gate: asyncio.Event | None = None
        self.installed_list_error: Exception | None = None
        self.installed_channel = "latest/stable"
        self.installed_version = "1.2.3"
        self.installed_rows = [
            {
                "name": "py-rand-tool",
                "summary": "CLI tool",
                "tracking-channel": "latest/edge",
                "base": "core26",
                "version": "0.1",
                "revision": 1,
            },
            {
                "name": "core26",
                "summary": "Base snap",
                "tracking-channel": "latest/stable",
                "base": "bare",
                "version": "26",
            },
            {"summary": "row without a name is skipped"},
        ]

    async def _install(self, **kwargs):
        self.installed_names.add(kwargs.get("snap"))
        return SimpleNamespace(change="1")

    async def _remove(self, name, **kwargs):
        self.installed_names.discard(name)
        return SimpleNamespace(change="2")

    async def request(self, method: str, endpoint: str, **kwargs):
        self.requests.append(endpoint)
        if endpoint == "snaps":
            if self.installed_list_gate is not None:
                await self.installed_list_gate.wait()
            if self.installed_list_error is not None:
                raise self.installed_list_error
            return _response({"result": self.installed_rows})
        if endpoint.startswith("snaps/"):
            name = endpoint.split("/", 1)[1]
            if name in self.installed_names:
                return _response(
                    {
                        "result": {
                            "name": name,
                            "base": "core26",
                            "tracking-channel": self.installed_channel,
                            "version": self.installed_version,
                            "revision": 7,
                        }
                    }
                )
            raise _http_error(404, endpoint)
        raise AssertionError(f"unexpected endpoint {endpoint}")

    async def get_changes_by_id_generator(self, change_id):
        while True:
            for change in self.changes:
                yield change
            if not self.loop_changes:
                return
            await asyncio.sleep(0)


READY_CHANGE = ChangesResponse.model_validate(
    {
        "status-code": 200,
        "type": "sync",
        "status": "OK",
        "result": {
            "id": "1",
            "kind": "install-snap",
            "summary": "Install snap",
            "status": "Done",
            "ready": True,
            "spawn-time": "2024-09-13T19:57:32.170327+00:00",
            "ready-time": "2024-09-13T19:58:32.170327+00:00",
            "tasks": [
                {
                    "id": "1",
                    "kind": "install",
                    "summary": "Installing py-rand-tool",
                    "status": "Done",
                    "progress": {"label": "install", "done": 1, "total": 1},
                    "spawn-time": "2024-09-13T19:57:32.170327+00:00",
                    "ready-time": "2024-09-13T19:58:32.170327+00:00",
                }
            ],
        },
    }
)


class LinkScreen(ModalScreen[None]):
    def __init__(self) -> None:
        super().__init__()
        self.allowed = ClickableLink(
            "Website", "https://snapcraft.io/vlc", id="allowed-link"
        )
        self.snap_link = ClickableLink("App Center", "snap://vlc", id="snap-link")
        self.file_link = ClickableLink("File", "file:///etc/passwd", id="file-link")
        self.empty_link = ClickableLink("Empty", "", id="empty-link")

    def compose(self) -> ComposeResult:
        yield self.allowed
        yield self.snap_link
        yield self.file_link
        yield self.empty_link


async def settle(app: StoreApp, pilot) -> None:
    await app.workers.wait_for_complete()
    await pilot.pause()


async def wait_until(pilot, predicate, attempts: int = 100) -> bool:
    for _ in range(attempts):
        if predicate():
            return True
        await pilot.pause()
    return predicate()


async def open_category_screen(app, pilot) -> CategoryScreen:
    await pilot.press("c")
    assert await wait_until(pilot, lambda: isinstance(app.screen, CategoryScreen))
    return app.screen


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


def make_app(client: FakeClient, preload_snap: str | None = None) -> StoreApp:
    return StoreApp(client=client, preload_snap=preload_snap)


def test_import_of_main_has_no_side_effects() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import store_tui.main"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_create_client_uses_store_defaults() -> None:
    client = create_client()
    assert client.store_headers["Snap-Device-Series"] == "16"
    assert client.store_headers["X-Ubuntu-Series"] == "16"
    asyncio.run(close_client(client))


async def test_startup_renders_featured_rows_and_title(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

        table = app.query_one(DataTable)
        assert table.row_count == 16
        assert len(table.columns) == 2
        assert app.mode is BrowseMode.FEATURED
        assert app.title == "store-tui - Featured"
        assert str(app.position_count.renderable) == "1/16"
        assert app.snapd_available is True


async def test_category_selection_updates_rows_and_title(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await open_category_screen(app, pilot)

        option_list = screen.query_one(OptionList)
        option_list.highlighted = app.categories.index("development")
        await pilot.press("enter")
        await settle(app, pilot)

        client.store.get_top_snaps_from_category.assert_awaited_with("development")
        assert app.mode is BrowseMode.CATEGORY
        assert app.title == "store-tui - Development"
        assert app.query_one(DataTable).row_count == 16


async def test_category_escape_dismisses_and_app_stays_usable(
    client: FakeClient,
) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await open_category_screen(app, pilot)

        await pilot.press("escape")
        assert await wait_until(
            pilot, lambda: not isinstance(app.screen, CategoryScreen)
        )
        await pilot.pause()

        assert app.mode is BrowseMode.FEATURED
        assert app.title == "store-tui - Featured"
        assert app.query_one(DataTable).row_count == 16
        client.store.get_top_snaps_from_category.assert_awaited_once_with("featured")


async def test_category_pressed_before_categories_load(client: FakeClient) -> None:
    gate = asyncio.Event()

    async def gated_categories():
        await gate.wait()
        return CATEGORIES

    client.store.get_categories = AsyncMock(side_effect=gated_categories)
    app = make_app(client)

    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        assert app.categories == []
        assert not isinstance(app.screen, CategoryScreen)

        gate.set()
        await settle(app, pilot)
        assert len(app.categories) == 20


async def test_search_passes_stripped_query(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))

        await pilot.press("space", "space", "v", "l", "c", "space", "space")
        await pilot.press("enter")
        await settle(app, pilot)

        assert client.store.find.await_count == 1
        assert client.store.find.await_args.kwargs["query"] == "vlc"
        assert client.store.find.await_args.kwargs["fields"] == [
            "title",
            "store-url",
            "summary",
        ]
        assert app.mode is BrowseMode.SEARCH
        assert app.search_query == "vlc"
        assert app.title == 'store-tui - Search: "vlc"'
        assert app.query_one(DataTable).row_count == 16


async def test_empty_search_is_ignored(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))

        await pilot.press("enter")
        await pilot.pause()

        assert client.store.find.await_count == 0
        assert app.mode is BrowseMode.FEATURED
        assert app.title == "store-tui - Featured"


async def test_search_cancel_does_not_search(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))

        await pilot.press("escape")
        assert await wait_until(pilot, lambda: not isinstance(app.screen, SearchScreen))
        await pilot.pause()

        assert client.store.find.await_count == 0
        assert app.query_one(DataTable).row_count == 16


async def test_row_selection_opens_snap_screen(client: FakeClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        app.query_one(DataTable).focus()
        await pilot.press("enter")
        await settle(app, pilot)

        assert isinstance(app.screen, SnapScreen)
        screen = app.screen
        assert screen.title == "py-rand-tool"
        client.store.retry_get_snap_info.assert_awaited_once()
        assert (
            client.store.retry_get_snap_info.await_args.kwargs["snap_name"] == "vivaldi"
        )

        texts = [str(label.renderable) for label in screen.query(".details-item")]
        assert "Supported: ✅ on amd64" in texts
        assert "Installed: ❌" in texts
        assert "Archs: amd64, armhf, ppc64el, s390x" in texts
        assert "License: unset" in texts
        assert len(screen.query(Footer)) == 1

        await pilot.press("escape")
        assert await wait_until(pilot, lambda: not isinstance(app.screen, SnapScreen))
        await pilot.pause()
        assert app.focused is app.results
        await pilot.press("down")
        assert app.results.cursor_row == 1


async def push_install_screen(
    app,
    pilot,
    info: InfoResponse,
    client,
    state: InstalledState | None = None,
) -> InstallScreen:
    screen = InstallScreen(
        snap_info=info,
        install_state=state or InstalledState(installed=False),
        client=client,
    )
    app.push_screen(screen)
    assert await wait_until(pilot, lambda: app.screen is screen)
    await pilot.pause()
    await settle(app, pilot)
    return screen


def progress_message(screen: InstallScreen) -> str:
    label = screen.progress.query(Label).first()
    return "" if label is None else str(label.renderable)


def list_names(list_view) -> list[str]:
    return [str(item.name) for item in list_view.children]


def risk_item_label(item) -> str:
    label = item.query(Label).first()
    return "" if label is None else str(label.renderable)


async def select_track(pilot, screen: InstallScreen, track: str) -> None:
    names = list_names(screen.track_list)
    assert track in names, f"{track} not in {names}"
    screen.track_list.index = names.index(track)
    await pilot.pause()
    await pilot.pause()


async def select_risk(pilot, screen: InstallScreen, risk: str) -> None:
    names = list_names(screen.risk_list)
    assert risk in names, f"{risk} not in {names}"
    screen.risk_list.index = names.index(risk)
    await pilot.pause()


async def choose_mode(pilot, screen: InstallScreen, mode: str) -> None:
    """Drive the mode list with real key presses, exercising Highlighted."""
    names = list_names(screen.mode_list)
    target = names.index(mode)
    screen.mode_list.focus()
    await pilot.pause()
    current = screen.mode_list.index or 0
    if current == target:
        # A key press is still needed to exercise the user path; return to the
        # same mode via the opposite direction.
        if target < len(names) - 1:
            await pilot.press("down", "up")
        else:
            await pilot.press("up", "down")
    else:
        key = "down" if target > current else "up"
        for _ in range(abs(target - current)):
            await pilot.press(key)
    await pilot.pause()
    await pilot.pause()
    assert screen.mode == mode


def mode_labels(screen: InstallScreen) -> list[str]:
    return [str(item.query_one(Label).renderable) for item in screen.mode_list.children]


def visible_rows(screen: InstallScreen) -> list[str]:
    """Text exactly as painted, one string per terminal row."""
    return [strip.text for strip in screen._compositor.render_strips()]


def count_visible(screen: InstallScreen, needle: str) -> int:
    return sum(row.count(needle) for row in visible_rows(screen))


def widget_visible_text(screen: InstallScreen, widget) -> str:
    region = widget.region
    rows = visible_rows(screen)
    lines = [
        rows[y][region.x : region.right]
        for y in range(region.y, min(region.bottom, len(rows)))
    ]
    return " ".join(" ".join(lines).split())


def notification_messages(app) -> list[str]:
    return [notification.message for notification in app._notifications]


def selected_modes(screen: InstallScreen) -> list[str]:
    return [
        str(item.name)
        for item in screen.mode_list.children
        if str(item.query_one(Label).renderable).startswith("●")
    ]


async def test_install_screen_mounts_with_channels(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO, client)

        assert len(screen.channels) == 1
        assert screen.channels[0].channel.name == "edge"
        assert list_names(screen.track_list) == ["latest"]
        assert list_names(screen.risk_list) == ["edge"]
        labels = [risk_item_label(item) for item in screen.risk_list.children]
        assert "edge · 0.1" in labels[0]
        assert screen.install_button.disabled is False
        assert str(screen.install_button.label) == "Install latest/edge"
        assert screen.uninstall_button.disabled is True
        assert "Install py-rand-tool" in str(screen.title_label.renderable)
        assert str(screen.subtitle_label.renderable) == "amd64 · Alexander Lukens"
        assert str(screen.badge_label.renderable) == "Not installed"

        # Installed state is queried once on mount, not on every highlight.
        assert client.requests.count("snaps/py-rand-tool") == 1

        screen.track_list.focus()
        await pilot.press("down", "up")
        await pilot.pause()
        assert client.requests.count("snaps/py-rand-tool") == 1


async def test_install_screen_without_channels_is_safe(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO_NO_CHANNELS, client)

        assert screen.channels == []
        assert screen.unavailable_label.display is True
        assert "No channels for amd64" in str(screen.unavailable_label.renderable)
        assert screen.install_button.disabled is True
        assert screen.uninstall_button.disabled is True
        assert list_names(screen.track_list) == []
        assert list_names(screen.risk_list) == []
        assert screen.selected_channel is None
        assert screen.release_title.display is False
        assert screen.release_details.display is False
        assert screen.mode_title.display is False
        assert screen.mode_list.display is False
        assert screen.mode_hint.display is False
        assert count_visible(screen, "No channels for amd64") == 1


async def test_installed_snap_without_channels_cannot_act(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.installed_names.add("arm-only")
    app = make_app(client)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        state = InstalledState(
            installed=True,
            version="1.2.3",
            revision=7,
            channel="latest/stable",
        )
        screen = await push_install_screen(
            app, pilot, SNAP_INFO_NO_CHANNELS, client, state=state
        )

        assert screen.is_installed is True
        assert screen.install_button.disabled is True
        assert screen.uninstall_button.disabled is True
        assert screen.release_title.display is False
        assert screen.mode_list.display is False
        assert count_visible(screen, "No channels for amd64") == 1

        await pilot.press("u")
        await pilot.pause()
        assert "No channels for amd64" in notification_messages(app)
        assert client.snaps.remove_snap.await_count == 0


def section_titles(screen: InstallScreen) -> list[str]:
    return [
        str(widget.renderable)
        for widget in screen.query(".section-title")
        if widget.display
    ]


async def test_install_section_headings_are_ordered(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO_MULTI_TRACK, client)
        assert section_titles(screen) == ["Track", "Risk", "Release", "Install mode"]

    app2 = make_app(client)
    async with app2.run_test(size=(120, 40)) as pilot:
        await settle(app2, pilot)
        screen = await push_install_screen(app2, pilot, SNAP_INFO_NO_CHANNELS, client)
        assert section_titles(screen) == ["Track", "Risk"]


async def test_install_screen_survives_snapd_unavailable(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.request = AsyncMock(side_effect=RuntimeError("snapd unavailable"))
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO, client)

        assert screen.install_state is not None
        assert screen.install_state.error is not None
        assert str(screen.badge_label.renderable) == "Installed state unavailable"
        assert screen.install_button.disabled is False
        assert screen.uninstall_button.disabled is True
        assert list_names(screen.risk_list) == ["edge"]


async def test_multi_track_fixture_drives_both_panes(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO_MULTI_TRACK, client)

        assert {item.channel.architecture for item in screen.channels} == {"amd64"}
        assert list_names(screen.track_list) == ["latest", "2.0", "1.0"]
        assert screen.selected_track == "latest"
        assert screen.selected_risk == "stable"
        assert list_names(screen.risk_list) == ["stable", "candidate", "beta", "edge"]

        labels = [risk_item_label(item) for item in screen.risk_list.children]
        assert labels == [
            "stable · 2.1.0",
            "candidate · 2.2.0-rc1",
            "beta · 2.2.0-beta2",
            "edge · 2.3.0-dev",
        ]

        await select_track(pilot, screen, "2.0")
        assert list_names(screen.risk_list) == ["stable", "beta"]
        assert screen.selected_risk == "stable"
        assert screen.selected_channel is not None
        assert screen.selected_channel.version == "2.0.4"
        assert [risk_item_label(item) for item in screen.risk_list.children] == [
            "stable · 2.0.4",
            "beta · 2.0.5-beta1",
        ]

        await select_track(pilot, screen, "1.0")
        assert list_names(screen.risk_list) == ["stable"]
        assert screen.selected_channel is not None
        assert screen.selected_channel.version == "1.0.9"

        await select_track(pilot, screen, "latest")
        await select_risk(pilot, screen, "edge")
        assert screen.selected_channel is not None
        assert screen.selected_channel.version == "2.3.0-dev"


async def test_default_selection_uses_installed_channel(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        client.installed_names.add("py-rand-tool")
        client.installed_channel = "2.0/beta"
        client.installed_version = "2.0.5-beta1"
        state = InstalledState(
            installed=True,
            version="2.0.5-beta1",
            revision=205,
            channel="2.0/beta",
        )
        screen = await push_install_screen(
            app, pilot, SNAP_INFO_MULTI_TRACK, client, state=state
        )

        assert screen.selected_track == "2.0"
        assert screen.selected_risk == "beta"
        assert screen.selected_channel is not None
        assert screen.selected_channel.version == "2.0.5-beta1"
        assert screen.track_list.index == 1
        assert screen.risk_list.index == 1
        assert screen.same_channel_installed is True
        assert screen.install_button.disabled is True
        assert str(screen.install_button.label) == "Installed from 2.0/beta"
        assert screen.uninstall_button.disabled is False
        assert "Manage py-rand-tool" in str(screen.title_label.renderable)
        assert str(screen.badge_label.renderable) == "Installed 2.0.5-beta1 on 2.0/beta"

        await select_track(pilot, screen, "latest")
        assert screen.selected_risk == "stable"
        assert str(screen.install_button.label) == "Switch to latest/stable"
        assert screen.install_button.disabled is False


async def test_classic_channel_preselects_classic_mode(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO_MULTI_TRACK, client)
        assert screen.mode == "strict"

        await select_risk(pilot, screen, "edge")
        assert screen.mode == "classic"
        assert screen.mode_list.index == 1
        assert selected_modes(screen) == ["classic"]
        assert "without sandboxing" in str(screen.mode_hint.renderable)

        await select_risk(pilot, screen, "stable")
        assert screen.mode == "strict"


async def test_mode_choice_persists_across_track_switch(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO_MULTI_TRACK, client)

        await choose_mode(pilot, screen, "devmode")
        assert screen.mode == "devmode"
        assert "logged" in str(screen.mode_hint.renderable)

        await select_track(pilot, screen, "2.0")
        assert screen.mode == "devmode"
        await select_risk(pilot, screen, "beta")
        assert screen.mode == "devmode"
        await select_track(pilot, screen, "latest")
        assert screen.mode == "devmode"

        await choose_mode(pilot, screen, "classic")
        await select_track(pilot, screen, "1.0")
        assert screen.mode == "classic"


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("strict", {"classic": False, "devmode": False, "jailmode": False}),
        ("classic", {"classic": True, "devmode": False, "jailmode": False}),
        ("devmode", {"classic": False, "devmode": True, "jailmode": False}),
        ("jailmode", {"classic": False, "devmode": False, "jailmode": True}),
    ],
)
async def test_mode_selection_maps_to_install_flags(
    client: FakeClient,
    monkeypatch,
    mode: str,
    expected: dict[str, bool],
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.changes = [READY_CHANGE]
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO, client)
        await choose_mode(pilot, screen, mode)
        assert screen._mode_explicit is True

        await pilot.click("#install-button")
        assert await wait_until(
            pilot,
            lambda: client.snaps.install_snap.await_count == 1
            and not screen._change_running,
        )

        kwargs = client.snaps.install_snap.await_args.kwargs
        assert kwargs["classic"] is expected["classic"]
        assert kwargs["devmode"] is expected["devmode"]
        assert kwargs["jailmode"] is expected["jailmode"]
        assert kwargs["dangerous"] is False
        assert kwargs["channel"] == "latest/edge"


async def test_install_error_change_shows_error_screen(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.changes = [ERROR_CHANGE]
    client.snaps.install_snap = AsyncMock(return_value=SimpleNamespace(change="1"))
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO, client)

        await choose_mode(pilot, screen, "classic")
        await pilot.click("#install-button")
        await settle(app, pilot)

        assert isinstance(app.screen, ErrorScreen)
        assert "cannot install snap" in app.screen.error_text
        assert progress_message(screen) == "Operation failed"
        assert screen.progress.display is False
        assert str(screen.status_label.renderable) == "Operation failed"
        kwargs = client.snaps.install_snap.await_args.kwargs
        assert kwargs["classic"] is True
        assert kwargs["dangerous"] is False
        assert screen.uninstall_button.disabled is True
        assert screen.install_button.disabled is False


async def test_change_stream_exhaustion_shows_error(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.changes = []
    client.loop_changes = False
    client.snaps.install_snap = AsyncMock(return_value=SimpleNamespace(change="1"))
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO, client)

        await pilot.click("#install-button")
        await settle(app, pilot)

        assert isinstance(app.screen, ErrorScreen)
        assert "change stream ended before completion" in app.screen.error_text
        assert progress_message(screen) == "Operation failed"


async def test_installed_error_clears_rows_and_updates_title(
    client: FakeClient,
) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        assert app.query_one(DataTable).row_count == 16

        client.installed_list_error = RuntimeError("snapd exploded")
        await pilot.press("i")
        await settle(app, pilot)

        assert isinstance(app.screen, ErrorScreen)
        assert "snapd exploded" in app.screen.error_text
        assert app.screen_stack[0].query_one(DataTable).row_count == 0
        assert app.mode is BrowseMode.INSTALLED
        assert app.title == "store-tui - Installed"
        assert str(app.position_count.renderable) == "0/0"
        assert app.empty_state.display is True
        assert str(app.empty_state.renderable) == "No snaps installed"


async def test_installed_snapd_unavailable_clears_rows(client: FakeClient) -> None:
    client.ping = AsyncMock(return_value=SimpleNamespace(status_code=503))
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        assert app.snapd_available is False

        await pilot.press("i")
        await settle(app, pilot)

        assert isinstance(app.screen, ErrorScreen)
        assert app.screen_stack[0].query_one(DataTable).row_count == 0
        assert app.title == "store-tui - Installed"


async def test_installed_list_uses_lenient_snapd_rows(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        await settle(app, pilot)

        assert not isinstance(app.screen, ErrorScreen)
        table = app.query_one(DataTable)
        assert table.row_count == 2
        assert app.title == "store-tui - Installed"
        assert app.empty_state.display is False


async def test_snapd_layer_tolerates_core26_and_missing_fields(
    client: FakeClient,
) -> None:
    client.installed_names.add("py-rand-tool")
    state = await get_installed_state(client, "py-rand-tool")
    assert state.installed is True
    assert state.version == "1.2.3"
    assert state.channel == "latest/stable"
    assert state.error is None

    missing = await get_installed_state(client, "missing")
    assert missing.installed is False
    assert missing.error is None

    rows = await list_installed(client)
    assert [row.name for row in rows] == ["core26", "py-rand-tool"]
    assert rows[1].channel == "latest/edge"

    client.installed_list_error = RuntimeError("boom")
    with pytest.raises(SnapdError):
        await list_installed(client)


async def test_snap_label_unknown_when_snapd_unreachable(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.ping = AsyncMock(return_value=SimpleNamespace(status_code=503))
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        app.query_one(DataTable).focus()
        await pilot.press("enter")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SnapScreen))
        await settle(app, pilot)

        texts = [str(label.renderable) for label in app.screen.query(".details-item")]
        assert "Installed: ❓ (could not query snapd)" in texts


async def test_late_installed_failure_does_not_clobber_newer_search(
    client: FakeClient,
) -> None:
    gate = asyncio.Event()
    client.installed_list_gate = gate
    client.installed_list_error = RuntimeError("late installed failure")
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        assert await wait_until(pilot, lambda: "snaps" in client.requests)

        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        await pilot.press("v", "l", "c", "enter")
        assert await wait_until(
            pilot,
            lambda: app.mode is BrowseMode.SEARCH
            and app.query_one(DataTable).row_count == 16,
        )

        gate.set()
        await settle(app, pilot)

        assert not isinstance(app.screen, ErrorScreen)
        assert app.mode is BrowseMode.SEARCH
        assert app.title == 'store-tui - Search: "vlc"'
        assert app.query_one(DataTable).row_count == 16


async def test_duplicate_result_names_do_not_crash(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

        count = app.results.set_rows(
            [
                ResultRow(name="vivaldi", summary="one"),
                ResultRow(name="vivaldi", summary="two"),
            ]
        )

        assert count == 1
        assert app.query_one(DataTable).row_count == 1
        assert str(app.position_count.renderable) == "1/1"


async def test_empty_state_is_shown_and_hidden(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        assert app.empty_state.display is False

        client.store.find = AsyncMock(return_value=SearchResponse(results=[]))
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        await pilot.press("n", "o", "p", "e", "enter")
        await settle(app, pilot)

        assert app.query_one(DataTable).row_count == 0
        assert app.empty_state.display is True
        assert str(app.empty_state.renderable) == "No results"
        assert app.empty_state.styles.text_align == "center"

        client.store.find = AsyncMock(return_value=FEATURED)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        await pilot.press("v", "l", "c", "enter")
        await settle(app, pilot)

        assert app.query_one(DataTable).row_count == 16
        assert app.empty_state.display is False


async def test_successful_install_updates_buttons_and_snap_screen(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.changes = [READY_CHANGE]
    client.installed_channel = "latest/edge"

    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        app.query_one(DataTable).focus()
        await pilot.press("enter")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SnapScreen))
        await settle(app, pilot)
        snap_screen = app.screen

        await pilot.press("i")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstallScreen))
        await pilot.pause()
        install_screen = app.screen

        assert install_screen.install_button.disabled is False
        await pilot.click("#install-button")
        assert await wait_until(
            pilot,
            lambda: client.snaps.install_snap.await_count == 1
            and not install_screen._change_running,
        )
        await pilot.pause()

        kwargs = client.snaps.install_snap.await_args.kwargs
        assert kwargs["snap"] == "py-rand-tool"
        assert kwargs["channel"] == "latest/edge"
        assert kwargs["classic"] is False
        assert kwargs["dangerous"] is False
        assert kwargs["devmode"] is False
        assert kwargs["jailmode"] is False
        assert kwargs["wait"] is False
        assert install_screen._change_running is False
        assert progress_message(install_screen) == "Operation complete"
        assert install_screen.progress.display is False
        assert install_screen.status_label.display is True
        assert (
            str(install_screen.status_label.renderable)
            == "Installed py-rand-tool from latest/edge"
        )
        assert install_screen.uninstall_button.disabled is False
        assert install_screen.install_state is not None
        assert install_screen.install_state.installed is True
        assert str(install_screen.install_button.label) == "Installed from latest/edge"
        assert install_screen.install_button.disabled is True
        assert "Manage py-rand-tool" in str(install_screen.title_label.renderable)

        await pilot.press("escape")
        assert await wait_until(pilot, lambda: app.screen is snap_screen)
        await wait_until(
            pilot,
            lambda: "Installed: ✅"
            in str(snap_screen.query_one("#is-installed-label", Label).renderable),
        )
        assert "1.2.3" in str(
            snap_screen.query_one("#is-installed-label", Label).renderable
        )


async def test_successful_uninstall_updates_state(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.changes = [READY_CHANGE]
    client.installed_names.add("py-rand-tool")
    client.installed_channel = "latest/edge"

    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        app.query_one(DataTable).focus()
        await pilot.press("enter")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SnapScreen))
        await settle(app, pilot)
        snap_screen = app.screen

        await pilot.press("i")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstallScreen))
        await pilot.pause()
        install_screen = app.screen

        assert install_screen.uninstall_button.disabled is False
        await pilot.click("#uninstall-button")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.pause()
        assert client.snaps.remove_snap.await_count == 0
        assert "purged" in str(
            app.screen.query_one("#confirm-message", Label).renderable
        )

        await pilot.click("#confirm-confirm")
        assert await wait_until(
            pilot,
            lambda: client.snaps.remove_snap.await_count == 1
            and not install_screen._change_running,
        )
        await pilot.pause()
        assert app.screen is install_screen

        assert client.snaps.remove_snap.await_args.args[0] == "py-rand-tool"
        assert client.snaps.remove_snap.await_args.kwargs == {
            "purge": True,
            "terminate": True,
            "wait": False,
        }
        assert progress_message(install_screen) == "Operation complete"
        assert install_screen.progress.display is False
        assert (
            str(install_screen.status_label.renderable)
            == "Removed py-rand-tool and its data"
        )
        assert install_screen.install_button.disabled is False
        assert install_screen.uninstall_button.disabled is True
        assert install_screen.install_state is not None
        assert install_screen.install_state.installed is False

        await pilot.press("escape")
        assert await wait_until(pilot, lambda: app.screen is snap_screen)


async def test_dismiss_is_ignored_while_change_running(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    release = asyncio.Event()

    async def gated_changes(change_id):
        await release.wait()
        yield READY_CHANGE

    client.get_changes_by_id_generator = gated_changes
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        app.query_one(DataTable).focus()
        await pilot.press("enter")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SnapScreen))
        await settle(app, pilot)
        snap_screen = app.screen

        await pilot.press("i")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstallScreen))
        await pilot.pause()
        install_screen = app.screen

        await pilot.click("#install-button")
        assert await wait_until(
            pilot, lambda: client.snaps.install_snap.await_count == 1
        )

        await pilot.press("escape")
        await pilot.pause()
        assert app.screen is install_screen
        assert "Operation in progress" in progress_message(install_screen)
        assert install_screen.progress.display is True
        assert install_screen.status_label.display is True
        assert "Operation in progress" in str(install_screen.status_label.renderable)
        assert len(app._notifications) >= 1

        await pilot.press("i")
        await pilot.pause()
        assert "Operation in progress — please wait" in notification_messages(app)
        assert client.snaps.install_snap.await_count == 1

        release.set()
        assert await wait_until(pilot, lambda: not install_screen._change_running)

        await pilot.press("escape")
        assert await wait_until(pilot, lambda: app.screen is snap_screen)
        await wait_until(
            pilot,
            lambda: "Installed: ✅"
            in str(snap_screen.query_one("#is-installed-label", Label).renderable),
        )


async def test_teardown_mid_change_does_not_raise(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )

    async def never_complete(change_id):
        await asyncio.Event().wait()
        if False:  # pragma: no cover - ensure this is an async generator
            yield None

    client.get_changes_by_id_generator = never_complete
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO, client)
        await pilot.click("#install-button")
        assert await wait_until(
            pilot, lambda: client.snaps.install_snap.await_count == 1
        )
        assert screen._change_running is True


async def test_uninstall_confirmation_cancel_sends_nothing(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.installed_names.add("py-rand-tool")
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO, client)
        assert screen.uninstall_button.disabled is False

        await pilot.press("u")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.pause()
        confirm = app.screen
        assert "Remove py-rand-tool and all of its data?" in str(
            confirm.query_one("#confirm-message", Label).renderable
        )
        await pilot.click("#confirm-cancel")
        assert await wait_until(pilot, lambda: app.screen is screen)
        await pilot.pause()
        assert client.snaps.remove_snap.await_count == 0

        await pilot.press("u")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ConfirmScreen))
        await pilot.press("escape")
        assert await wait_until(pilot, lambda: app.screen is screen)
        await pilot.pause()
        assert client.snaps.remove_snap.await_count == 0


async def test_progress_and_status_hidden_while_idle(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO, client)

        assert screen.progress.display is False
        assert screen.status_label.display is False
        assert str(screen.status_label.renderable) == ""


async def test_release_details_are_aligned_key_value_rows(
    client: FakeClient, monkeypatch
) -> None:
    from rich.console import Console

    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO_MULTI_TRACK, client)

        console = Console(width=80, record=True)
        console.print(screen.release_details.renderable)
        text = console.export_text()
        lines = [line for line in text.splitlines() if line.strip()]

        released_at = screen.selected_channel.channel.released_at
        assert released_at is not None
        humanized = humanize.naturaltime(released_at)

        for expected in ("Version", "2.1.0", "Revision", "210", "Size", "7.3 MB"):
            assert expected in text
        assert f"{humanized} (2024-10-01)" in text
        assert "Confinement" in text and "strict" in text

        version_line = next(line for line in lines if line.startswith("Version"))
        revision_line = next(line for line in lines if line.startswith("Revision"))
        released_line = next(line for line in lines if line.startswith("Released"))
        assert version_line.index("2.1.0") == revision_line.index("210")
        assert version_line.index("2.1.0") == released_line.index(humanized)


async def test_installed_channel_marker_moves_with_track(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        client.installed_names.add("py-rand-tool")
        client.installed_channel = "2.0/beta"
        client.installed_version = "2.0.5-beta1"
        state = InstalledState(
            installed=True,
            version="2.0.5-beta1",
            revision=205,
            channel="2.0/beta",
        )
        screen = await push_install_screen(
            app, pilot, SNAP_INFO_MULTI_TRACK, client, state=state
        )

        labels = [risk_item_label(item) for item in screen.risk_list.children]
        assert labels[1].startswith("● beta · 2.0.5-beta1")
        assert not labels[0].startswith("●")

        await select_track(pilot, screen, "latest")
        labels = [risk_item_label(item) for item in screen.risk_list.children]
        assert not any(label.startswith("●") for label in labels)


def info_with_tracks(*tracks: str) -> InfoResponse:
    """Clone the multi-track fixture with extra stable-only tracks."""
    data = deepcopy(SNAP_INFO_MULTI_TRACK.model_dump(by_alias=True, mode="json"))
    base = next(
        item
        for item in data["channel-map"]
        if item["channel"]["track"] == "latest" and item["channel"]["name"] == "stable"
    )
    for track in tracks:
        item = deepcopy(base)
        item["channel"]["track"] = track
        item["channel"]["name"] = "stable"
        item["channel"]["risk"] = "stable"
        data["channel-map"].append(item)
    return InfoResponse.model_validate(data)


async def test_track_pane_width_derives_from_labels(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    long_info = info_with_tracks("k8s-1.30", "ubuntu-22.04")

    app = make_app(client)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, long_info, client)
        await pilot.pause()

        longest = max(len(track) for track in screen.tracks)
        assert screen.track_list.region.width == max(12, min(26, longest + 3))
        assert screen.track_list.size.width >= len("k8s-1.30")
        assert screen.track_list.size.width >= len("ubuntu-22.04")
        for item in screen.track_list.children:
            label = item.query_one(Label)
            assert label.region.width == len(str(label.renderable))
            assert label.region.width <= screen.track_list.size.width
            assert label.region.right <= screen.track_list.region.right - 1
        assert_visible_regions_contained(screen)

    app2 = make_app(client)
    async with app2.run_test(size=(80, 24)) as pilot:
        await settle(app2, pilot)
        screen = await push_install_screen(app2, pilot, SNAP_INFO_MULTI_TRACK, client)
        await pilot.pause()

        assert screen.track_list.region.width == 12
        for item in screen.track_list.children:
            label = item.query_one(Label)
            assert label.region.width == len(str(label.renderable))
            assert label.region.right <= screen.track_list.region.right - 1
        assert_visible_regions_contained(screen)


async def test_keyboard_shortcuts_and_focus_order(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.installed_names.add("py-rand-tool")
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO, client)

        assert screen.active_bindings["escape"].binding.action == "dismiss_screen"
        assert screen.active_bindings["q"].binding.action == "dismiss_screen"
        assert screen.active_bindings["i"].binding.action == "start_install"
        assert screen.active_bindings["u"].binding.action == "request_uninstall"

        screen.track_list.focus()
        await pilot.pause()
        await pilot.press("tab")
        assert app.focused is screen.risk_list
        await pilot.press("tab")
        assert app.focused is screen.mode_list
        await pilot.press("tab")
        assert app.focused is screen.install_button
        await pilot.press("tab")
        assert app.focused is screen.uninstall_button
        await pilot.press("shift+tab")
        assert app.focused is screen.install_button


def assert_visible_regions_contained(screen: InstallScreen) -> None:
    """Every painted widget must fit inside its parent and have a real area."""
    for widget in screen.walk_children():
        node = widget
        shown = True
        while node is not None:
            if not node.display or not getattr(node, "visible", True):
                shown = False
                break
            node = node.parent
        if not shown:
            continue

        region = widget.region
        name = f"{type(widget).__name__}#{widget.id or ''}"
        assert region.width > 0 and region.height > 0, name

        parent = widget.parent
        assert parent is not None, name
        parent_region = parent.region
        assert region.x >= parent_region.x, name
        assert region.y >= parent_region.y, name
        assert region.right <= parent_region.right, name
        assert region.bottom <= parent_region.bottom, name


@pytest.mark.parametrize("size", [(120, 40), (80, 24)])
@pytest.mark.parametrize("installed", [False, True])
async def test_install_screen_layout_fits(
    client: FakeClient,
    monkeypatch,
    size: tuple[int, int],
    installed: bool,
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    state = InstalledState(installed=False)
    if installed:
        client.installed_names.add("py-rand-tool")
        client.installed_channel = "latest/edge"
        client.installed_version = "1.2.3"
        state = InstalledState(
            installed=True,
            version="1.2.3",
            revision=7,
            channel="latest/edge",
        )

    app = make_app(client)
    async with app.run_test(size=size) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(
            app, pilot, SNAP_INFO_MULTI_TRACK, client, state=state
        )
        await pilot.pause()

        assert screen.size.width == size[0]
        for selector in (
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
        ):
            region = screen.query_one(selector).region
            assert region.width > 0 and region.height > 0, selector
            assert region.right <= size[0], selector
            assert region.bottom <= size[1], selector

        assert_visible_regions_contained(screen)

        install_region = screen.install_button.region
        uninstall_region = screen.uninstall_button.region
        assert install_region.width >= len(str(screen.install_button.label))
        assert uninstall_region.width >= len(str(screen.uninstall_button.label))
        assert install_region.right <= uninstall_region.x


async def test_mode_marker_unique_across_automatic_and_explicit_changes(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.installed_names.add("py-rand-tool")
    client.installed_channel = "latest/edge"
    client.installed_version = "1.2.3"
    app = make_app(client)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        state = InstalledState(
            installed=True,
            version="1.2.3",
            revision=7,
            channel="latest/edge",
        )
        screen = await push_install_screen(
            app, pilot, SNAP_INFO_MULTI_TRACK, client, state=state
        )

        assert screen.mode == "classic"
        assert screen._mode_explicit is False
        assert selected_modes(screen) == ["classic"]
        assert screen.mode_list.index == 1

        await select_risk(pilot, screen, "stable")
        assert screen.mode == "strict"
        assert screen._mode_explicit is False
        assert selected_modes(screen) == ["strict"]
        assert screen.mode_list.index == 0
        assert all("●" not in label for label in mode_labels(screen)[1:])

        await select_risk(pilot, screen, "edge")
        assert screen.mode == "classic"
        assert screen._mode_explicit is False
        assert selected_modes(screen) == ["classic"]
        assert screen.mode_list.index == 1
        assert all("●" not in label for label in mode_labels(screen)[:1])

        await choose_mode(pilot, screen, "devmode")
        assert screen.mode == "devmode"
        assert screen._mode_explicit is True
        assert selected_modes(screen) == ["devmode"]

        await select_track(pilot, screen, "2.0")
        assert screen.mode == "devmode"
        assert screen._mode_explicit is True
        assert selected_modes(screen) == ["devmode"]
        assert screen.mode_list.index == 2


async def test_mode_hint_renders_complete_at_80x24(
    client: FakeClient, monkeypatch
) -> None:
    from store_tui.channels import MODE_HINTS, MODES

    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO_MULTI_TRACK, client)

        for mode in MODES:
            await choose_mode(pilot, screen, mode)
            await pilot.pause()
            assert screen.mode_hint.region.right <= screen.side.region.right
            assert widget_visible_text(screen, screen.mode_hint) == MODE_HINTS[mode]


async def test_longest_risk_label_fits_at_80x24(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.installed_names.add("py-rand-tool")
    client.installed_channel = "latest/candidate"
    client.installed_version = "2.2.0-rc1"
    app = make_app(client)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(app, pilot)
        state = InstalledState(
            installed=True,
            version="2.2.0-rc1",
            revision=220,
            channel="latest/candidate",
        )
        screen = await push_install_screen(
            app, pilot, SNAP_INFO_MULTI_TRACK, client, state=state
        )
        await pilot.pause()

        inner_right = screen.risk_list.region.right - 1
        for item in screen.risk_list.children:
            label = item.query_one(Label)
            assert label.region.right <= inner_right
            assert label.region.width <= screen.risk_list.size.width

        assert (
            "● candidate · 2.2.0-rc1"
            in visible_rows(screen)[screen.risk_list.region.y + 2]
        )
        assert screen.risk_list.max_scroll_x == 0


async def test_all_mode_rows_visible_at_80x24(client: FakeClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=(80, 24)) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO_MULTI_TRACK, client)
        await pilot.pause()

        assert screen.mode_list.region.height == 4
        assert screen.mode_list.region.bottom <= screen.side.region.bottom
        assert screen.mode_hint.region.bottom <= screen.side.region.bottom
        assert screen.mode_list.max_scroll_y == 0
        for item in screen.mode_list.children:
            assert item.region.height == 1
            assert item.region.bottom <= screen.mode_list.region.bottom
            assert item.region.right <= screen.side.region.right


async def test_unavailable_actions_notify_instead_of_silence(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client)
    async with app.run_test(size=(120, 40)) as pilot:
        await settle(app, pilot)
        await push_install_screen(app, pilot, SNAP_INFO, client)

        await pilot.press("u")
        await pilot.pause()
        assert (
            "Nothing to uninstall — py-rand-tool is not installed"
            in notification_messages(app)
        )
        assert client.snaps.remove_snap.await_count == 0

    same_channel = FakeClient()
    same_channel.installed_names.add("py-rand-tool")
    same_channel.installed_channel = "latest/edge"
    app2 = make_app(same_channel)
    async with app2.run_test(size=(120, 40)) as pilot:
        await settle(app2, pilot)
        await push_install_screen(app2, pilot, SNAP_INFO, same_channel)

        await pilot.press("i")
        await pilot.pause()
        assert "Already installed from latest/edge" in notification_messages(app2)
        assert same_channel.snaps.install_snap.await_count == 0

    no_channels = FakeClient()
    app3 = make_app(no_channels)
    async with app3.run_test(size=(120, 40)) as pilot:
        await settle(app3, pilot)
        await push_install_screen(app3, pilot, SNAP_INFO_NO_CHANNELS, no_channels)

        await pilot.press("i")
        await pilot.pause()
        assert "No channels for amd64" in notification_messages(app3)
        assert no_channels.snaps.install_snap.await_count == 0
        await pilot.press("u")
        await pilot.pause()
        assert notification_messages(app3).count("No channels for amd64") == 2
        assert no_channels.snaps.install_snap.await_count == 0
        assert no_channels.snaps.remove_snap.await_count == 0


async def test_same_channel_requires_full_channel_string(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.installed_names.add("py-rand-tool")
    client.installed_channel = "latest/edge"
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await push_install_screen(app, pilot, SNAP_INFO, client)
        assert screen.same_channel_installed is True
        assert screen.install_button.disabled is True
        assert str(screen.install_button.label) == "Installed from latest/edge"

        await pilot.press("i")
        await pilot.pause()
        assert client.snaps.install_snap.await_count == 0

    client2 = FakeClient()
    client2.installed_names.add("py-rand-tool")
    client2.installed_channel = "edge"
    app2 = make_app(client2)
    async with app2.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app2, pilot)
        screen = await push_install_screen(app2, pilot, SNAP_INFO, client2)
        assert screen.same_channel_installed is False
        assert screen.install_button.disabled is False
        assert str(screen.install_button.label) == "Switch to latest/edge"


async def test_no_duplicate_dom_ids(client: FakeClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )

    def ids_of(widget) -> list[str]:
        return [
            child.id
            for child in widget.walk_children(with_self=True)
            if child.id is not None
        ]

    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        main_ids = ids_of(app.screen)
        assert len(main_ids) == len(set(main_ids))

        install = await push_install_screen(app, pilot, SNAP_INFO, client)
        install_ids = ids_of(install)
        assert len(install_ids) == len(set(install_ids))
        assert "track-list" in install_ids
        assert "risk-list" in install_ids
        assert "mode-list" in install_ids
        assert "install-progress" in install_ids

        app.pop_screen()
        await pilot.pause()
        app.query_one(DataTable).focus()
        await pilot.press("enter")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SnapScreen))
        snap_ids = ids_of(app.screen)
        assert len(snap_ids) == len(set(snap_ids))


async def test_category_and_search_screens_have_footer_hints(
    client: FakeClient,
) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = await open_category_screen(app, pilot)
        assert len(screen.query(Footer)) == 1
        escape_binding = screen.active_bindings["escape"].binding
        assert escape_binding.action == "dismiss_screen"
        assert escape_binding.description == "Back"
        await pilot.press("escape")
        assert await wait_until(
            pilot, lambda: not isinstance(app.screen, CategoryScreen)
        )

        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        assert len(app.screen.query(Footer)) == 1
        assert app.screen.active_bindings["escape"].binding.description == "Back"
        await pilot.press("escape")
        assert await wait_until(pilot, lambda: not isinstance(app.screen, SearchScreen))


async def test_show_error_updates_existing_error_screen(
    client: FakeClient,
) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        app.show_error(RuntimeError("first"), "Error - one")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ErrorScreen))

        app.show_error(RuntimeError("second"), "Error - two")
        await pilot.pause()

        errors = [
            screen for screen in app.screen_stack if isinstance(screen, ErrorScreen)
        ]
        assert len(errors) == 1
        assert "second" in app.screen.error_text
        assert str(app.screen.query_one("#error-title", Label).renderable) == (
            "Error - two"
        )


async def test_error_formatting_survives_broken_str(client: FakeClient) -> None:
    class Broken:
        def __str__(self) -> str:
            raise RuntimeError("no str for you")

    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        app.show_error(Broken(), "Error - broken")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ErrorScreen))
        assert "unprintable" in app.screen.error_text


async def test_startup_error_skips_preload(client: FakeClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    client.store.get_top_snaps_from_category = AsyncMock(
        side_effect=RuntimeError("featured down")
    )
    app = make_app(client, preload_snap="py-rand-tool")
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

        assert isinstance(app.screen, ErrorScreen)
        assert client.store.retry_get_snap_info.await_count == 0


async def test_preload_survives_user_intervention_during_startup(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    gate = asyncio.Event()

    async def gated_categories():
        await gate.wait()
        return CATEGORIES

    client.store.get_categories = AsyncMock(side_effect=gated_categories)
    app = make_app(client, preload_snap="py-rand-tool")
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await pilot.pause()
        await pilot.press("i")
        await wait_until(pilot, lambda: app.mode is BrowseMode.INSTALLED)

        gate.set()
        await settle(app, pilot)
        assert await wait_until(pilot, lambda: isinstance(app.screen, SnapScreen))


async def test_normalize_snap_name() -> None:
    from store_tui.main import build_parser, normalize_snap_name

    assert normalize_snap_name("snap://vlc") == "vlc"
    assert normalize_snap_name("  vlc  ") == "vlc"
    assert normalize_snap_name(None) is None
    assert normalize_snap_name("snap://") is None
    assert build_parser().parse_args([]).snap is None
    assert build_parser().parse_args(["snap://vlc"]).snap == "snap://vlc"


async def test_close_client_runs_on_app_exit() -> None:
    client = FakeClient()
    client.snapd_client = SimpleNamespace(aclose=AsyncMock())
    client.store.store_client = SimpleNamespace(aclose=AsyncMock())
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

    client.snapd_client.aclose.assert_awaited_once()
    client.store.store_client.aclose.assert_awaited_once()


async def test_progress_bar_transitions_do_not_raise(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        progress = ProgressBarWithMessage()
        app.screen.mount(progress)
        await pilot.pause()

        progress.update_progress(0, None, "Starting…")
        progress.update_progress(5, 10, "Working…")
        progress.update_progress(10, 10, "Operation complete")

        bar = progress.query_one(ProgressBar)
        assert bar.total == 10
        assert bar.progress == 10
        label = progress.query(Label).first()
        assert label is not None
        assert str(label.renderable) == "Operation complete"


async def test_progress_unknown_total_with_progress_stays_empty(
    client: FakeClient,
) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        progress = ProgressBarWithMessage()
        app.screen.mount(progress)
        await pilot.pause()

        progress.update_progress(7, None, "Working…")
        bar = progress.query_one(ProgressBar)
        assert bar.total == 1
        assert bar.progress == 0


async def test_clickable_link_allowlist_is_non_blocking(
    client: FakeClient, monkeypatch
) -> None:
    from store_tui import launcher

    spawned: list[list[str]] = []

    def fake_run(argv, *, tolerate_running):
        spawned.append(argv)
        return True, None

    monkeypatch.setattr(launcher, "_run", fake_run)
    monkeypatch.setattr(
        launcher, "find_snap_store_binary", lambda: "/usr/bin/snap-store"
    )

    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = LinkScreen()
        app.push_screen(screen)
        assert await wait_until(pilot, lambda: app.screen is screen)
        await pilot.pause()

        opened = MagicMock()
        monkeypatch.setattr(app, "open_url", opened)

        for link in (
            screen.allowed,
            screen.snap_link,
            screen.file_link,
            screen.empty_link,
        ):
            link.on_link_clicked()

        await app.workers.wait_for_complete()
        await pilot.pause()

        # http(s) still goes through Textual; the snap link goes through the
        # native launcher; the disallowed file/empty links do nothing.
        assert opened.call_count == 1
        assert opened.call_args.args[0] == "https://snapcraft.io/vlc"
        assert spawned == [["/usr/bin/snap-store", "snap://vlc"]]
        assert notification_messages(app) == []


async def test_failing_snap_launch_notifies_without_browser(
    client: FakeClient, monkeypatch
) -> None:
    from store_tui import launcher

    monkeypatch.setattr(launcher, "find_snap_store_binary", lambda: None)
    monkeypatch.setattr(launcher, "snap_url_handler", lambda: "store-tui.desktop")
    monkeypatch.setattr(
        launcher, "_run", lambda argv, *, tolerate_running: (False, "boom")
    )

    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        screen = LinkScreen()
        app.push_screen(screen)
        assert await wait_until(pilot, lambda: app.screen is screen)
        await pilot.pause()

        opened = MagicMock()
        monkeypatch.setattr(app, "open_url", opened)

        screen.snap_link.on_link_clicked()
        await app.workers.wait_for_complete()
        await pilot.pause()

        # No blank browser page: the failure is surfaced as a warning instead.
        opened.assert_not_called()
        assert "Could not open App Center — is it installed?" in notification_messages(
            app
        )


async def test_preload_snap_opens_details(client: FakeClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    app = make_app(client, preload_snap="py-rand-tool")
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

        assert isinstance(app.screen, SnapScreen)
        assert (
            client.store.retry_get_snap_info.await_args.kwargs["snap_name"]
            == "py-rand-tool"
        )


def info_with_description(paragraphs: int) -> InfoResponse:
    data = deepcopy(SNAP_INFO.model_dump(by_alias=True, mode="json"))
    body = "\n\n".join(
        f"Paragraph {index}: " + "lorem ipsum dolor sit amet " * 12
        for index in range(paragraphs)
    )
    data["snap"]["description"] = body
    return InfoResponse.model_validate(data)


class StubSnapdClient:
    def __init__(self, response) -> None:
        self.response = response
        self.calls: list[str] = []

    async def request(self, method: str, endpoint: str, **kwargs):
        self.calls.append(endpoint)
        return self.response


async def test_long_description_scrolls_within_card(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )

    async def measure(paragraphs: int) -> tuple[int, int]:
        app = make_app(client)
        async with app.run_test(size=(80, 24)) as pilot:
            await settle(app, pilot)
            screen = SnapScreen(
                snap_name="py-rand-tool",
                snap_info=info_with_description(paragraphs),
                install_state=InstalledState(installed=False),
                client=client,
            )
            app.push_screen(screen)
            assert await wait_until(pilot, lambda: app.screen is screen)
            for _ in range(5):
                await pilot.pause()
            scroll = screen.query_one("#snap-scroll", VerticalScroll)
            markdown = screen.query_one(Markdown)
            if paragraphs > 1:
                assert markdown.region.height > scroll.size.height
                assert scroll.styles.scrollbar_size_vertical == 1
            return markdown.region.height, scroll.max_scroll_y

    short_height, short_scroll = await measure(1)
    long_height, long_scroll = await measure(60)

    assert long_height > short_height
    assert long_scroll > short_scroll
    assert long_scroll > 0


async def test_get_installed_state_rejects_bad_envelopes() -> None:
    error_envelope = StubSnapdClient(
        _response(
            {
                "type": "error",
                "status-code": 200,
                "status": "error",
                "result": {"message": "not installed"},
            }
        )
    )
    state = await get_installed_state(error_envelope, "py-rand-tool")
    assert state.installed is False
    assert state.error is not None

    empty_result = StubSnapdClient(
        _response({"type": "sync", "status-code": 200, "result": {}})
    )
    state = await get_installed_state(empty_result, "py-rand-tool")
    assert state.installed is False
    assert state.error is not None

    ok = StubSnapdClient(
        _response(
            {
                "type": "sync",
                "status-code": 200,
                "result": {
                    "name": "py-rand-tool",
                    "version": "1.0",
                    "tracking-channel": "latest/edge",
                    "revision": 3,
                },
            }
        )
    )
    state = await get_installed_state(ok, "py-rand-tool")
    assert state.installed is True
    assert state.error is None
    assert state.version == "1.0"
    assert state.channel == "latest/edge"

    bad_status = StubSnapdClient(
        _response({"type": "sync", "status-code": 500, "result": {"name": "x"}})
    )
    state = await get_installed_state(bad_status, "x")
    assert state.installed is False
    assert "500" in (state.error or "")


async def test_installed_snap_with_ubuntu_26_04_fields_is_accepted(
    client: FakeClient, monkeypatch
) -> None:
    """A modern snapd reports grade/mounted-size and friends; they must be ignored."""
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    installed = {
        "name": "py-rand-tool",
        "id": "py-rand-tool-id",
        "base": "core26",
        "confinement": "strict",
        "grade": "stable",
        "status": "active",
        "channel": "stable",
        "tracking-channel": "latest/stable",
        "version": "3.0.21",
        "revision": 1234,
        "installed-size": 200_000_000,
        "mounted-size": 210_000_000,
        "mounted-from": "/var/lib/snapd/snaps/py-rand-tool_1234.snap",
        "ignore-validation": False,
        "devmode": False,
        "jailmode": False,
        "contact": "https://example.invalid/support",
        "publisher": {
            "id": "publisher-id",
            "username": "rand",
            "display-name": "Rand Tools",
            "validation": "verified",
        },
        "apps": [{"name": "py-rand-tool", "daemon": "", "enabled": True}],
        "summary": "CLI tool",
    }
    envelope = {"type": "sync", "status-code": 200, "status": "OK"}

    async def fake_request(method: str, endpoint: str, **kwargs):
        client.requests.append(endpoint)
        if endpoint == "snaps":
            return _response({**envelope, "result": [installed]})
        if endpoint == "snaps/py-rand-tool":
            return _response({**envelope, "result": installed})
        raise AssertionError(f"unexpected endpoint {endpoint}")

    client.request = AsyncMock(side_effect=fake_request)

    state = await get_installed_state(client, "py-rand-tool")
    assert state.installed is True
    assert state.error is None
    assert state.version == "3.0.21"
    assert state.channel == "latest/stable"
    assert state.revision == 1234

    rows = await list_installed(client)
    assert [(row.name, row.version, row.channel) for row in rows] == [
        ("py-rand-tool", "3.0.21", "latest/stable")
    ]

    app = make_app(client, preload_snap="py-rand-tool")
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        assert await wait_until(pilot, lambda: isinstance(app.screen, SnapScreen))
        await settle(app, pilot)
        assert (
            str(app.screen.query_one("#is-installed-label", Label).renderable)
            == "Installed: ✅ (3.0.21)"
        )
