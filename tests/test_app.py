"""End-to-end UI tests for the 0.2.0 store-tui surface."""

from __future__ import annotations

import asyncio
import pathlib
import subprocess
import sys
from unittest.mock import AsyncMock

import pytest
from rich_pixels import Pixels
from snap_python.utils import SnapdAPIError
from textual.widgets import Checkbox, DataTable, Input, Label, OptionList, Select

from store_tui.app import (
    PREVIEW_ICON_PATH,
    BrowseMode,
    StoreApp,
    format_preview,
)
from store_tui.screens.activity import ActivityScreen
from store_tui.screens.category import CategoryScreen
from store_tui.screens.error import ErrorScreen
from store_tui.screens.installed import InstalledScreen
from store_tui.screens.search import SearchScreen
from store_tui.screens.snap import SnapScreen
from store_tui.widgets.results_table import ResultRow
from tests.support import (
    CATEGORIES,
    FEATURED,
    READY_CHANGE,
    SNAP_INFO,
    FakeClient,
    change,
    changes_list,
    installed_list,
    installed_snap,
    paginated,
    with_snap_info,
)

REPO_ROOT = pathlib.Path(__file__).parent.parent
TERMINAL_SIZE = (120, 40)


async def settle(app: StoreApp, pilot) -> None:
    await app.workers.wait_for_complete()
    await pilot.pause()


async def wait_until(pilot, predicate, attempts: int = 100) -> bool:
    for _ in range(attempts):
        if predicate():
            return True
        await pilot.pause()
    return predicate()


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


async def test_startup_renders_featured_rows_and_title(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

        table = app.query_one(DataTable)
        assert table.row_count == 16
        assert len(table.columns) == 3
        assert app.mode is BrowseMode.FEATURED
        assert app.title == "store-tui - Featured"
        assert str(app.position_count.renderable) == "1/16"
        assert app.snapd_available is True


def test_format_preview_includes_store_metadata() -> None:
    text = format_preview(
        ResultRow(
            name="vlc",
            title="VLC media player",
            publisher="VideoLAN",
            summary="The ultimate media player",
            version="3.0.20",
            revision=3078,
            channel="stable",
            confinement="strict",
            base="core22",
            type="app",
            store_url="https://snapcraft.io/vlc",
        )
    )
    plain = text.plain
    assert "VLC media player  (vlc)" in plain
    assert "VideoLAN" in plain
    assert "Version: 3.0.20" in plain
    assert "Revision: 3078" in plain
    assert "Channel: stable" in plain
    assert "Confinement: strict" in plain
    assert "Base: core22" in plain
    assert "Type: app" in plain
    assert "Enter for full details" in plain


async def test_startup_preview_updates_with_highlight(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

        preview = app.details.renderable
        assert "Vivaldi" in preview.plain
        assert "A Powerful. Personal. Private." in preview.plain
        assert "https://snapcraft.io/vivaldi" in preview.plain

        await pilot.press("down")
        await pilot.pause()
        assert "opentofu" in app.details.renderable.plain


async def test_main_table_wraps_long_descriptions(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(app, pilot)

        table = app.results
        assert table.max_scroll_x == 0
        heights = {row.key.value: row.height for row in table.ordered_rows}
        assert heights["kstars"] >= 2
        row = table.get_row("kstars")
        assert "desktop planetarium for amateur and professional astronomers" in str(
            row[2]
        )


async def test_main_preview_stacks_when_too_narrow(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=(120, 30)) as pilot:
        await settle(app, pilot)

        body = app.query_one("#store-body")
        results_pane = app.query_one("#results-pane")
        details_pane = app.query_one("#store-details-pane")
        icon = app.query_one("#store-icon")
        details = app.query_one("#store-details")
        assert not body.has_class("narrow")
        assert app.results.max_scroll_x == 0
        assert icon.region.y < details.region.y

        await pilot.resize_terminal(90, 30)
        await settle(app, pilot)
        assert body.has_class("narrow")
        assert details_pane.region.width == 90
        assert details_pane.region.y > results_pane.region.y
        assert icon.region.x > details.region.x

        await pilot.resize_terminal(120, 30)
        await settle(app, pilot)
        assert not body.has_class("narrow")
        assert details_pane.region.x > results_pane.region.x
        assert icon.region.y < details.region.y


async def test_preview_prefetches_icons_in_batches_of_ten(
    client: FakeClient, monkeypatch
) -> None:
    icon = Pixels.from_image_path(PREVIEW_ICON_PATH, resize=(4, 4))
    gate = asyncio.Event()
    requested: list[str] = []
    active = 0

    async def fake_fetch(self, url: str) -> Pixels | None:
        nonlocal active
        requested.append(url)
        active += 1
        try:
            await gate.wait()
        finally:
            active -= 1
        return icon

    monkeypatch.setattr(StoreApp, "_fetch_preview_icon", fake_fetch)
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        rows = [
            ResultRow(
                name=f"snap{index}",
                title=f"Snap {index}",
                icon_url=f"https://icons.test/{index}.png",
            )
            for index in range(15)
        ]
        app._apply_rows(rows)

        assert await wait_until(pilot, lambda: len(requested) == 10)
        assert active == 10

        app.results.move_cursor(row=14)
        await pilot.pause()
        assert len(requested) == 10
        assert active == 10

        gate.set()
        assert await wait_until(pilot, lambda: "https://icons.test/14.png" in requested)
        assert await wait_until(
            pilot,
            lambda: app._icon_cache.get("https://icons.test/14.png") is icon,
        )
        await pilot.pause()
        assert app.icon.renderable is icon


async def test_preview_resolves_icon_without_search_media(
    client: FakeClient, monkeypatch
) -> None:
    icon = Pixels.from_image_path(PREVIEW_ICON_PATH, resize=(4, 4))
    url = "https://icons.test/alpha.png"

    async def fake_fetch(self, icon_url: str) -> Pixels | None:
        assert icon_url == url
        return icon

    monkeypatch.setattr(StoreApp, "_fetch_preview_icon", fake_fetch)
    client.store.get_snap_info.return_value = with_snap_info(
        SNAP_INFO,
        snap={"name": "alpha", "media": [{"type": "icon", "url": url}]},
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        app._apply_rows([ResultRow(name="alpha", title="Alpha")])

        assert await wait_until(pilot, lambda: app._icon_cache.get(url) is icon)
        await pilot.pause()
        assert app.icon.renderable is icon
        assert client.store.get_snap_info.await_args.kwargs["fields"] == ["media"]


async def test_category_selection_updates_rows_and_title(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("c")
        assert await wait_until(pilot, lambda: isinstance(app.screen, CategoryScreen))

        screen = app.screen
        option_list = screen.query_one(OptionList)
        option_list.highlighted = app.categories.index("development")
        await pilot.press("enter")
        await settle(app, pilot)

        assert client.store.find.await_args.kwargs["category"] == "development"
        assert app.mode is BrowseMode.CATEGORY
        assert app.title == "store-tui - Development"
        assert app.query_one(DataTable).row_count == 16


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


async def test_search_uses_paginated_store_endpoint(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))

        await pilot.press("v", "l", "c", "enter")
        await settle(app, pilot)

        kwargs = client.store.get_snap_search_paginated.await_args.kwargs
        assert kwargs["q"] == "vlc"
        assert kwargs["page"] == 1
        assert kwargs["arch"] == "wide"
        assert kwargs["confinement"] == "strict,classic"
        assert app.mode is BrowseMode.SEARCH
        assert app.search_query == "vlc"
        assert app.title == 'store-tui - Search: "vlc"'
        assert app.query_one(DataTable).row_count == 16


async def test_live_preview_then_submit_does_not_cancel_dialog(
    client: FakeClient,
) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        await pilot.press("v", "l", "c")
        await asyncio.sleep(0.45)
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)

        await pilot.press("enter")
        assert await wait_until(pilot, lambda: not isinstance(app.screen, SearchScreen))
        await settle(app, pilot)

        assert not isinstance(app.screen, ErrorScreen)
        assert app.search_request is not None
        assert app.search_request.query == "vlc"
        assert app.query_one(DataTable).row_count == 16


async def test_search_prefills_previous_query(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        await pilot.press("v", "l", "c", "enter")
        await settle(app, pilot)

        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        await pilot.pause()
        assert app.screen.query_one("#search-input", Input).value == "vlc"


async def test_search_prefills_previous_filters(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        screen = app.screen
        screen.query_one("#search-input", Input).value = "vlc"
        screen.query_one("#search-confinement", Select).value = "strict"
        screen.query_one("#search-category", Select).value = "games"
        screen.query_one("#search-publisher", Input).value = "Canonical"
        await pilot.pause()
        await pilot.click("#search-submit")
        await settle(app, pilot)

        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        await pilot.pause()
        screen = app.screen
        assert screen.query_one("#search-input", Input).value == "vlc"
        assert screen.query_one("#search-confinement", Select).value == "strict"
        assert screen.query_one("#search-category", Select).value == "games"
        assert screen.query_one("#search-publisher", Input).value == "Canonical"


async def test_filter_change_updates_background_results_live(
    client: FakeClient,
) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        await pilot.press("v", "l", "c", "enter")
        await settle(app, pilot)

        client.store.find = AsyncMock(
            return_value=FEATURED.model_copy(update={"results": FEATURED.results[:1]})
        )
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        screen = app.screen
        screen.query_one("#search-category", Select).value = "games"

        await asyncio.sleep(0.45)
        assert await wait_until(pilot, lambda: app.results.row_count == 1)

        assert isinstance(app.screen, SearchScreen)
        assert app.search_request is not None
        assert app.search_request.filters.category == "games"
        assert client.store.find.await_args.kwargs["category"] == "games"


async def test_advanced_filters_use_find(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        screen = app.screen
        screen.query_one("#search-input", Input).value = "vlc"
        screen.query_one("#search-confinement", Select).value = "strict"
        screen.query_one("#search-category", Select).value = "games"
        screen.query_one("#search-architecture", Select).value = "amd64"
        screen.query_one("#search-publisher", Input).value = "Canonical"
        screen.query_one("#search-channel", Input).value = "edge"
        screen.query_one("#search-name-prefix", Input).value = "v"
        screen.query_one("#search-featured", Checkbox).value = True
        await pilot.pause()

        await pilot.click("#search-submit")
        await settle(app, pilot)

        kwargs = client.store.find.await_args.kwargs
        assert kwargs["query"] == "vlc"
        assert kwargs["confinement"] == "strict"
        assert kwargs["category"] == "games"
        assert kwargs["architecture"] == "amd64"
        assert kwargs["publisher"] == "Canonical"
        assert kwargs["channel"] == "edge"
        assert kwargs["name_startswith"] == "v"
        assert kwargs["featured"] is True
        assert client.store.get_snap_search_paginated.await_count == 0
        assert "strict, games, by Canonical" in app.title


async def test_empty_search_is_ignored(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))

        await pilot.press("enter")
        await pilot.pause()

        assert client.store.get_snap_search_paginated.await_count == 0
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

        assert client.store.get_snap_search_paginated.await_count == 0
        assert app.query_one(DataTable).row_count == 16


async def test_load_more_appends_unique_rows(client: FakeClient) -> None:
    client.store.get_snap_search_paginated = AsyncMock(
        side_effect=[
            paginated(["alpha", "beta"], page=1, total=150),
            paginated(["gamma", "delta"], page=2, total=150),
        ]
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        await pilot.press("x", "enter")
        await settle(app, pilot)
        assert app.query_one(DataTable).row_count == 2

        await pilot.press("m")
        await settle(app, pilot)

        assert app.query_one(DataTable).row_count == 4
        assert str(app.position_count.renderable) == "1/4"
        assert client.store.get_snap_search_paginated.await_args.kwargs["page"] == 2


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

        await pilot.press("escape")
        assert await wait_until(pilot, lambda: not isinstance(app.screen, SnapScreen))
        await pilot.pause()
        assert app.focused is app.results


async def test_installed_binding_opens_management_screen(
    client: FakeClient,
) -> None:
    client.snaps.list_installed_snaps.return_value = installed_list(
        [
            installed_snap("alpha"),
            installed_snap("beta", status="disabled", version="2.0"),
        ]
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstalledScreen))
        await settle(app, pilot)

        table = app.screen.query_one("#installed-table", DataTable)
        assert table.row_count == 2
        assert not app.screen.query_one("#installed-empty").display


async def test_installed_row_opens_store_page(client: FakeClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    client.snaps.list_installed_snaps.return_value = installed_list(
        [installed_snap("alpha", version="2.0.1")]
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstalledScreen))
        await settle(app, pilot)

        await pilot.click("#installed-table", offset=(2, 1))
        assert await wait_until(pilot, lambda: isinstance(app.screen, SnapScreen))
        screen = app.screen
        assert screen.snap_name == "alpha"
        assert (
            client.store.retry_get_snap_info.await_args.kwargs["snap_name"] == "alpha"
        )
        # The installed row already carries the state; no extra snapd query.
        client.snaps.get_installed_snap.assert_not_awaited()
        labels = [str(label.renderable) for label in screen.query(".details-item")]
        assert "Installed: ✅ (2.0.1) · latest/stable" in labels

        await pilot.press("escape")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstalledScreen))
        await settle(app, pilot)
        assert client.snaps.list_installed_snaps.await_count == 2

        await pilot.press("enter")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SnapScreen))
        await pilot.press("escape")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstalledScreen))


async def test_installed_layout_sizes_table_to_content(client: FakeClient) -> None:
    client.snaps.list_installed_snaps.return_value = installed_list(
        [
            installed_snap("alpha", summary="Short"),
            installed_snap(
                "beta",
                summary=(
                    "A considerably longer summary that must not change the width "
                    "of the details pane"
                ),
            ),
        ]
    )
    app = make_app(client)
    async with app.run_test(size=(100, 30)) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstalledScreen))
        await settle(app, pilot)

        screen = app.screen
        table = screen.query_one("#installed-table", DataTable)
        table_pane = screen.query_one("#installed-table-pane")
        details_pane = screen.query_one("#installed-details-pane")
        details = screen.query_one("#installed-details")

        assert table_pane.size.width == table.virtual_size.width
        assert table.max_scroll_x == 0
        right_width = details_pane.size.width
        details_width = details.size.width

        await pilot.press("down")
        await settle(app, pilot)
        assert "considerably longer" in str(details.renderable)
        assert details_pane.size.width == right_width
        assert details.size.width == details_width
        assert table.max_scroll_x == 0


async def test_installed_layout_stacks_when_too_narrow(client: FakeClient) -> None:
    client.snaps.list_installed_snaps.return_value = installed_list(
        [installed_snap("alpha"), installed_snap("beta")]
    )
    app = make_app(client)
    async with app.run_test(size=(100, 30)) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstalledScreen))
        await settle(app, pilot)

        screen = app.screen
        body = screen.query_one("#installed-body")
        assert not body.has_class("narrow")

        await pilot.resize_terminal(70, 30)
        await settle(app, pilot)
        assert body.has_class("narrow")
        table_pane = screen.query_one("#installed-table-pane")
        details_pane = screen.query_one("#installed-details-pane")
        assert details_pane.region.width == 70
        assert details_pane.region.y > table_pane.region.y

        await pilot.resize_terminal(100, 30)
        await settle(app, pilot)
        assert not body.has_class("narrow")
        assert details_pane.region.x > table_pane.region.x


async def test_installed_row_shows_loading_while_fetching_store_page(
    client: FakeClient, monkeypatch
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    monkeypatch.setattr(
        "store_tui.screens.install.get_platform_architecture", lambda: "amd64"
    )
    started = asyncio.Event()
    release = asyncio.Event()
    info = client.store.retry_get_snap_info.return_value

    async def fetch(**kwargs):
        started.set()
        await release.wait()
        return info

    client.store.retry_get_snap_info.side_effect = fetch
    client.snaps.list_installed_snaps.return_value = installed_list(
        [installed_snap("alpha")]
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("i")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstalledScreen))
        await settle(app, pilot)
        installed = app.screen

        await pilot.press("enter")
        assert await wait_until(pilot, started.is_set)
        assert installed.loading is True

        release.set()
        assert await wait_until(pilot, lambda: isinstance(app.screen, SnapScreen))
        await pilot.press("escape")
        assert await wait_until(pilot, lambda: isinstance(app.screen, InstalledScreen))
        await settle(app, pilot)
        assert installed.loading is False


async def test_activity_binding_opens_changes_screen(client: FakeClient) -> None:
    client.changes.list_changes.return_value = changes_list(
        [READY_CHANGE, change("2", summary="Auto refresh", kind="refresh-snap")]
    )
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        await pilot.press("a")
        assert await wait_until(pilot, lambda: isinstance(app.screen, ActivityScreen))
        await settle(app, pilot)

        table = app.screen.query_one("#activity-table", DataTable)
        assert table.row_count == 2


async def test_show_error_updates_existing_error_screen(client: FakeClient) -> None:
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


async def test_error_screen_prepends_snapd_kind_hint(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        app.show_error(
            SnapdAPIError("busy", kind="snap-change-conflict"), "Error - busy"
        )
        assert await wait_until(pilot, lambda: isinstance(app.screen, ErrorScreen))
        assert "Another snap operation is already in progress" in app.screen.error_text


async def test_startup_error_skips_preload(client: FakeClient, monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    client.store.find.side_effect = RuntimeError("featured down")
    app = make_app(client, preload_snap="py-rand-tool")
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

        assert isinstance(app.screen, ErrorScreen)
        assert client.store.retry_get_snap_info.await_count == 0


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


async def test_empty_state_is_shown_and_hidden(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)
        assert app.empty_state.display is False

        client.store.get_snap_search_paginated = AsyncMock(return_value=paginated([]))
        await pilot.press("s")
        assert await wait_until(pilot, lambda: isinstance(app.screen, SearchScreen))
        await pilot.press("n", "o", "p", "e", "enter")
        await settle(app, pilot)

        assert app.query_one(DataTable).row_count == 0
        assert app.empty_state.display is True
        assert str(app.empty_state.renderable) == "No results"


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


async def test_close_client_runs_on_app_exit() -> None:
    client = FakeClient()
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

    client.close.assert_awaited_once()


async def test_results_table_append_skips_duplicates(client: FakeClient) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

        app.results.set_rows([ResultRow(name="a")])
        total = app.results.append_rows([ResultRow(name="a"), ResultRow(name="b")])

        assert total == 2
        assert str(app.position_count.renderable) == "1/2"


async def test_results_table_append_preserves_cursor_position(
    client: FakeClient,
) -> None:
    app = make_app(client)
    async with app.run_test(size=TERMINAL_SIZE) as pilot:
        await settle(app, pilot)

        app.results.set_rows([ResultRow(name=name) for name in "abcd"])
        app.results.move_cursor(row=2)
        await pilot.pause()
        assert str(app.position_count.renderable) == "3/4"

        app.results.append_rows([ResultRow(name="e"), ResultRow(name="f")])
        await pilot.pause()
        assert str(app.position_count.renderable) == "3/6"


def test_search_filters_still_advanced_for_find() -> None:
    from store_tui.search import SearchFilters

    assert SearchFilters(confinement="strict", architecture="amd64").advanced is False
    assert SearchFilters(category="games").advanced is True
    assert SearchFilters().find_kwargs() == {}


def test_featured_fixture_is_valid() -> None:
    assert len(FEATURED.results) == 16
