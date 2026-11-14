"""The Snap Store TUI application."""

from __future__ import annotations

import asyncio
import logging
from enum import Enum

from snap_python.schemas.store.info import VALID_SNAP_INFO_FIELDS
from snap_python.schemas.store.search import SearchResponse
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, Label

from store_tui.client import close_client
from store_tui.screens.category import CategoryScreen
from store_tui.screens.error import ErrorScreen
from store_tui.screens.search import SearchScreen
from store_tui.screens.snap import SnapScreen
from store_tui.snapd import InstalledState, get_installed_state, list_installed
from store_tui.widgets.results_table import (
    PositionCount,
    ResultRow,
    ResultsTable,
    rows_from_search_response,
)

logger = logging.getLogger(__name__)

FEATURED_CATEGORY = "featured"
SEARCH_FIELDS = ["title", "store-url", "summary"]


class BrowseMode(Enum):
    FEATURED = "Featured"
    CATEGORY = "Category"
    SEARCH = "Search"
    INSTALLED = "Installed"


class StoreApp(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "choose_category", "Category"),
        ("s", "search_snaps", "Search"),
        ("i", "list_installed_snaps", "Installed"),
    ]
    CSS_PATH = "styles/app.tcss"

    def __init__(self, client, preload_snap: str | None = None) -> None:
        super().__init__()
        self.client = client
        self.preload_snap = preload_snap

        self.mode = BrowseMode.FEATURED
        self.category = FEATURED_CATEGORY
        self.search_query = ""
        self.categories: list[str] = []
        self.snapd_available = False
        self._generation = 0

        self.position_count = PositionCount(id="position-count")
        self.results = ResultsTable(self.position_count, id="results-table")
        self.empty_state = Label("", id="empty-state")
        self.empty_state.display = False
        self.update_title()

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        yield Header()
        yield self.results
        yield self.empty_state
        with Horizontal(id="footer"):
            yield Footer(show_command_palette=False)
            yield self.position_count

    async def on_mount(self) -> None:
        self.results.loading = True
        self.run_worker(
            self._startup(), group="startup", name="startup", exclusive=True
        )

    async def on_unmount(self) -> None:
        await close_client(self.client)

    # ------------------------------------------------------------------ state
    def _browse_label(self) -> str:
        if self.mode is BrowseMode.CATEGORY:
            return self.category.replace("-", " ").title()
        if self.mode is BrowseMode.SEARCH:
            return f'Search: "{self.search_query}"'
        return self.mode.value

    def update_title(self) -> None:
        self.title = f"store-tui - {self._browse_label()}"

    def _begin_browse(
        self,
        mode: BrowseMode,
        *,
        category: str | None = None,
        query: str | None = None,
    ) -> int:
        self._generation += 1
        self.mode = mode
        if category is not None:
            self.category = category
        if query is not None:
            self.search_query = query
        self.update_title()
        return self._generation

    def _empty_message(self) -> str:
        if self.mode is BrowseMode.INSTALLED:
            return "No snaps installed"
        return "No results"

    def _apply_rows(self, rows: list[ResultRow]) -> None:
        count = self.results.set_rows(rows)
        self.empty_state.update(self._empty_message())
        self.empty_state.display = count == 0

    def show_error(self, error: BaseException | str | object, title: str) -> None:
        """Surface an error, updating an existing error screen if one is open."""
        current = self.screen
        if isinstance(current, ErrorScreen):
            current.set_error(error, title)
            return
        self.push_screen(ErrorScreen(error, title))

    # ------------------------------------------------------------------ startup
    async def _probe_snapd(self) -> bool:
        try:
            response = await self.client.ping()
        except Exception:
            self.snapd_available = False
            return False
        status = getattr(response, "status_code", None)
        self.snapd_available = isinstance(status, int) and 200 <= status < 300
        return self.snapd_available

    async def _startup(self) -> None:
        generation = self._generation
        self.results.loading = True
        categories, featured, _available = await asyncio.gather(
            self.client.store.get_categories(),
            self.client.store.get_top_snaps_from_category(FEATURED_CATEGORY),
            self._probe_snapd(),
            return_exceptions=True,
        )

        errors: list[BaseException] = []

        if isinstance(categories, BaseException):
            errors.append(categories)
            self.categories = [FEATURED_CATEGORY]
        else:
            names = [
                category.name
                for category in (getattr(categories, "categories", None) or [])
                if category.name
            ]
            self.categories = names or [FEATURED_CATEGORY]

        if isinstance(featured, BaseException):
            errors.append(featured)
            featured = None
        elif not isinstance(featured, SearchResponse):
            featured = None

        if generation == self._generation:
            self._apply_rows(rows_from_search_response(featured))
            self.results.loading = False
            if self.results.row_count:
                self.results.focus()
            if errors:
                self.show_error(errors[0], "Error - loading the Snap Store")

        # Start-up failures must not push a snap screen over the error screen.
        if self.preload_snap and not errors:
            await self.open_snap(self.preload_snap)

    # ------------------------------------------------------------------ browsing
    async def _load_rows(self, generation: int, awaitable, error_title: str) -> None:
        self.results.loading = True
        try:
            response = await awaitable
        except Exception as error:
            response = None
            if generation == self._generation:
                self.show_error(error, error_title)
        finally:
            if generation == self._generation:
                self.results.loading = False
        if generation != self._generation:
            return
        if not isinstance(response, SearchResponse):
            response = None
        self._apply_rows(rows_from_search_response(response))

    def action_choose_category(self) -> None:
        self.run_worker(self._choose_category(), group="browse", name="browse-category")

    async def _choose_category(self) -> None:
        if not self.categories:
            # Categories have not loaded (or failed); stay usable and do nothing.
            return
        selected = await self.push_screen(
            CategoryScreen(self.categories, current=self.category),
            wait_for_dismiss=True,
        )
        if selected is None:
            return
        category = str(selected)
        if not category:
            return
        generation = self._begin_browse(BrowseMode.CATEGORY, category=category)
        await self._load_rows(
            generation,
            self.client.store.get_top_snaps_from_category(category),
            "Error - loading category",
        )

    def action_search_snaps(self) -> None:
        self.run_worker(self._search_snaps(), group="browse", name="browse-search")

    async def _search_snaps(self) -> None:
        value = await self.push_screen(SearchScreen(), wait_for_dismiss=True)
        if value is None:
            return
        query = str(value).strip()
        if not query:
            return
        generation = self._begin_browse(BrowseMode.SEARCH, query=query)
        await self._load_rows(
            generation,
            self.client.store.find(query=query, fields=SEARCH_FIELDS),
            "Error - searching snaps",
        )

    def action_list_installed_snaps(self) -> None:
        self.run_worker(
            self._list_installed_snaps(), group="browse", name="browse-installed"
        )

    async def _list_installed_snaps(self) -> None:
        generation = self._begin_browse(BrowseMode.INSTALLED)
        self.results.loading = True

        available = await self._probe_snapd()
        if generation != self._generation:
            return
        if not available:
            self.results.loading = False
            self._apply_rows([])
            self.show_error(
                ConnectionError(
                    "Snapd API not available - is the snapd-control interface connected?"
                ),
                "Error - listing installed snaps",
            )
            return

        try:
            installed_rows = await list_installed(self.client)
        except Exception as error:
            if generation == self._generation:
                self._apply_rows([])
                self.show_error(error, "Error - listing installed snaps")
            return
        finally:
            if generation == self._generation:
                self.results.loading = False

        if generation != self._generation:
            return
        self._apply_rows(
            [ResultRow(name=row.name, summary=row.summary) for row in installed_rows]
        )

    # ------------------------------------------------------------------ snap details
    async def _installed_state(self, snap_name: str) -> InstalledState:
        if not self.snapd_available:
            return InstalledState(installed=False, error="snapd API not available")
        return await get_installed_state(self.client, snap_name)

    async def open_snap(self, snap_name: str) -> None:
        if not snap_name:
            return
        self.results.loading = True
        try:
            snap_info, install_state = await asyncio.gather(
                self.client.store.retry_get_snap_info(
                    snap_name=snap_name, fields=VALID_SNAP_INFO_FIELDS
                ),
                self._installed_state(snap_name),
            )
        except Exception as error:
            self.show_error(error, "Error - retrieving snap info")
            return
        finally:
            self.results.loading = False

        if snap_info is None or getattr(snap_info, "snap", None) is None:
            self.show_error(
                ValueError(f"Snap {snap_name!r} was not found in the store"),
                "Error - retrieving snap info",
            )
            return
        self.push_screen(
            SnapScreen(
                snap_name=snap_name,
                snap_info=snap_info,
                install_state=install_state,
                client=self.client,
            )
        )

    @on(DataTable.RowSelected)
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table is not self.results:
            return
        snap_name = event.row_key.value
        if not snap_name:
            return
        self.run_worker(
            self.open_snap(str(snap_name)),
            group="snap-detail",
            name="snap-detail",
            exclusive=True,
        )
