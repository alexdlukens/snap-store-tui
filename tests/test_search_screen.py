"""SearchScreen form behavior."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from textual.app import App, ComposeResult
from textual.pilot import Pilot
from textual.widgets import Checkbox, Input, Select

from store_tui.screens.search import SearchScreen
from store_tui.search import SearchFilters, SearchRequest

UNSET = object()


class SearchHost(App[None]):
    """Minimal host that pushes the search modal and records its result."""

    def __init__(
        self,
        categories: list[str] | None = None,
        *,
        initial: SearchRequest | None = None,
    ) -> None:
        super().__init__()
        self.categories = categories
        self.initial = initial
        self.result: object = UNSET
        self.previews: list[SearchRequest] = []

    def compose(self) -> ComposeResult:
        yield from ()

    def on_mount(self) -> None:
        self.push_screen(
            SearchScreen(
                self.categories, initial=self.initial, on_change=self.previews.append
            ),
            callback=self._capture,
        )

    def _capture(self, result: SearchRequest | None) -> None:
        self.result = result


async def wait_for(pilot: Pilot, predicate: Callable[[], bool]) -> None:
    for _ in range(50):
        if predicate():
            return
        await pilot.pause()
    raise AssertionError("condition was not reached")


async def test_empty_request_cancels() -> None:
    app = SearchHost()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SearchScreen)
        assert app.screen.query_one("#search-input", Input).has_focus

        await pilot.press("enter")
        await wait_for(pilot, lambda: app.result is not UNSET)

        assert app.result is None
        assert not isinstance(app.screen, SearchScreen)


async def test_query_only_request_is_returned() -> None:
    app = SearchHost()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.screen.query_one("#search-input", Input).value = "  vlc  "

        await pilot.click("#search-submit")
        await wait_for(pilot, lambda: app.result is not UNSET)

        assert app.result == SearchRequest(query="vlc")


async def test_filters_survive_into_the_request() -> None:
    app = SearchHost(["games", "development"])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        screen.query_one("#search-input", Input).value = "vlc"
        screen.query_one("#search-confinement", Select).value = "strict"
        screen.query_one("#search-category", Select).value = "games"
        screen.query_one("#search-architecture", Select).value = "arm64"
        screen.query_one("#search-publisher", Input).value = "  Canonical  "
        screen.query_one("#search-channel", Input).value = " edge "
        screen.query_one("#search-name-prefix", Input).value = " snap "
        screen.query_one("#search-featured", Checkbox).value = True
        await pilot.pause()

        await pilot.click("#search-submit")
        await wait_for(pilot, lambda: app.result is not UNSET)

        assert app.result == SearchRequest(
            query="vlc",
            filters=SearchFilters(
                confinement="strict",
                category="games",
                publisher="Canonical",
                architecture="arm64",
                channel="edge",
                name_startswith="snap",
                featured=True,
            ),
        )


async def test_escape_dismisses_with_none() -> None:
    app = SearchHost()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("escape")
        await wait_for(pilot, lambda: app.result is not UNSET)

        assert app.result is None
        assert not isinstance(app.screen, SearchScreen)


async def test_enter_in_query_input_submits() -> None:
    app = SearchHost()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()

        await pilot.press("f", "i", "r", "e", "f", "o", "x", "enter")
        await wait_for(pilot, lambda: app.result is not UNSET)

        assert app.result == SearchRequest(query="firefox")


async def test_initial_request_prefills_the_form() -> None:
    initial = SearchRequest(
        query="vlc",
        filters=SearchFilters(
            confinement="strict",
            category="games",
            publisher="Canonical",
            architecture="arm64",
            channel="edge",
            name_startswith="v",
            featured=True,
        ),
    )
    app = SearchHost(["development"], initial=initial)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen

        assert screen.query_one("#search-input", Input).value == "vlc"
        assert screen.query_one("#search-confinement", Select).value == "strict"
        assert screen.query_one("#search-category", Select).value == "games"
        assert screen.query_one("#search-architecture", Select).value == "arm64"
        assert screen.query_one("#search-publisher", Input).value == "Canonical"
        assert screen.query_one("#search-channel", Input).value == "edge"
        assert screen.query_one("#search-name-prefix", Input).value == "v"
        assert screen.query_one("#search-featured", Checkbox).value is True

        await asyncio.sleep(0.45)
        await pilot.pause()
        assert app.previews == []


async def test_query_typing_emits_debounced_preview() -> None:
    app = SearchHost()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("v", "l", "c")
        await asyncio.sleep(0.45)
        await pilot.pause()

        assert app.previews
        assert app.previews[-1] == SearchRequest(query="vlc")


async def test_filter_change_emits_preview() -> None:
    app = SearchHost(["games"])
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        screen = app.screen
        screen.query_one("#search-category", Select).value = "games"
        await asyncio.sleep(0.45)
        await pilot.pause()

        assert app.previews
        assert app.previews[-1].filters.category == "games"


async def test_escape_cancels_pending_preview() -> None:
    app = SearchHost()
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        await pilot.press("v")
        await pilot.press("escape")
        await wait_for(pilot, lambda: app.result is not UNSET)
        await asyncio.sleep(0.45)
        await pilot.pause()

        assert app.previews == []
