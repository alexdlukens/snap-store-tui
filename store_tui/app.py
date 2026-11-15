"""The Snap Store TUI application."""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from pathlib import Path

from rich.text import Text
from rich_pixels import Pixels
from snap_python.schemas.store.info import VALID_SNAP_INFO_FIELDS
from snap_python.schemas.store.search import SearchResponse
from textual import events, on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import DataTable, Footer, Header, Label, Static

from store_tui.client import client_available, close_client
from store_tui.icons import IconCache
from store_tui.screens.activity import ActivityScreen
from store_tui.screens.category import CategoryScreen
from store_tui.screens.error import ErrorScreen
from store_tui.screens.installed import InstalledScreen
from store_tui.screens.search import SearchScreen
from store_tui.screens.snap import SnapScreen
from store_tui.search import (
    SEARCH_FIELDS,
    SearchRequest,
    paginated_arch,
    paginated_confinement,
    rows_from_paginated_response,
    rows_from_response,
)
from store_tui.snapd import InstalledState, get_installed_state
from store_tui.widgets.results_table import (
    PositionCount,
    ResultRow,
    ResultsTable,
)

logger = logging.getLogger(__name__)

FEATURED_CATEGORY = "featured"
SEARCH_PAGE_SIZE = 100
MIN_PREVIEW_WIDTH = 40
TABLE_SCROLLBAR_ALLOWANCE = 2
PREVIEW_ICON_SIZE = (12, 12)
MAX_ICON_FETCHES = 10
PREVIEW_ICON_PATH = Path(__file__).resolve().parent / "assets" / "placeholder.png"


def _placeholder_pixels() -> Pixels | None:
    try:
        return Pixels.from_image_path(PREVIEW_ICON_PATH, resize=PREVIEW_ICON_SIZE)
    except Exception:
        return None


def format_preview(row: ResultRow) -> Text:
    """Render the selected result without fetching the full store page."""
    text = Text()
    text.append(row.title or row.name, style="bold")
    if row.title and row.title != row.name:
        text.append(f"  ({row.name})", style="dim")
    text.append("\n")
    if row.publisher:
        text.append(row.publisher, style="dim")
        text.append("\n")
    text.append("\n")
    text.append(row.summary or "No summary provided.", style="italic")
    text.append("\n\n")
    for label, value in (
        ("Version", row.version),
        ("Revision", row.revision),
        ("Channel", row.channel),
        ("Confinement", row.confinement),
        ("Base", row.base),
        ("Type", row.type),
    ):
        if value not in (None, ""):
            text.append(f"{label}: ", style="bold")
            text.append(str(value))
            text.append("\n")
    if row.store_url:
        text.append("\n")
        text.append(row.store_url, style="dim")
    text.append("\n")
    text.append("Enter for full details", style="dim")
    return text


class BrowseMode(Enum):
    FEATURED = "Featured"
    CATEGORY = "Category"
    SEARCH = "Search"


class StoreApp(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "choose_category", "Category"),
        ("s", "search_snaps", "Search"),
        ("i", "show_installed", "Installed"),
        ("a", "show_activity", "Activity"),
        ("m", "load_more", "More"),
    ]
    CSS_PATH = "styles/app.tcss"

    def __init__(self, client, preload_snap: str | None = None) -> None:
        super().__init__()
        self.client = client
        self.preload_snap = preload_snap

        self.mode = BrowseMode.FEATURED
        self.category = FEATURED_CATEGORY
        self.search_query = ""
        self.search_request: SearchRequest | None = None
        self.search_page = 1
        self._search_has_more = False
        self._loading_more = False
        self.categories: list[str] = []
        self.snapd_available = False
        self._generation = 0

        self.position_count = PositionCount(id="position-count")
        self.results = ResultsTable(self.position_count, id="results-table")
        self.empty_state = Label("", id="empty-state")
        self.empty_state.display = False
        self._placeholder_icon = _placeholder_pixels()
        self.icon = Static(self._placeholder_icon or "", id="store-icon")
        self.icon.can_focus = False
        self.icon.styles.width = PREVIEW_ICON_SIZE[0]
        self.details = Static("", id="store-details")
        self.details.can_focus = False
        self._icon_urls: dict[str, str | None] = {}
        self._icon_pending: set[str] = set()
        self._icon_tasks: set[asyncio.Task] = set()
        self._icon_semaphore = asyncio.Semaphore(MAX_ICON_FETCHES)
        self.icons = IconCache()
        self._prefetch_cursor = 0
        self.store_body = Horizontal(id="store-body")
        self.update_title()

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        yield Header()
        with self.store_body:
            with Vertical(id="results-pane"):
                yield self.results
                yield self.empty_state
            with VerticalScroll(id="store-details-pane"), Vertical(id="store-preview"):
                yield self.details
                yield self.icon
        with Horizontal(id="footer"):
            yield Footer(show_command_palette=False)
            yield self.position_count

    async def on_mount(self) -> None:
        self._apply_layout()
        self.results.loading = True
        self.run_worker(
            self._startup(), group="startup", name="startup", exclusive=True
        )

    def on_resize(self, event: events.Resize) -> None:
        self._apply_layout()

    def _apply_layout(self) -> None:
        """Stack the preview below the results when side-by-side is too tight."""
        if not self.is_mounted:
            return
        minimum = self.results.min_content_width()
        narrow = (
            self.size.width < minimum + MIN_PREVIEW_WIDTH + TABLE_SCROLLBAR_ALLOWANCE
        )
        left_width = self.size.width if narrow else self.size.width - MIN_PREVIEW_WIDTH
        self.results.set_summary_width(
            self.results.summary_width_for(
                max(0, left_width - TABLE_SCROLLBAR_ALLOWANCE)
            )
        )
        self.store_body.set_class(narrow, "narrow")

    def _refresh_preview(self) -> None:
        if not self.is_mounted:
            return
        row = self.results.current_row()
        self.details.update(format_preview(row) if row is not None else Text(""))
        self._show_preview_icon(row)
        if row is None:
            return
        self._request_icon(row)
        if not self._icon_ready(row):
            index = self.results.get_row_index(row.name)
            if index >= self._prefetch_cursor:
                self._prefetch_batch(index)

    def _row_icon_url(self, row: ResultRow | None) -> str | None:
        if row is None:
            return None
        return row.icon_url or self._icon_urls.get(row.name)

    def _show_preview_icon(self, row: ResultRow | None) -> None:
        url = self._row_icon_url(row)
        pixels = (
            self.icons.cached_pixels(url, PREVIEW_ICON_SIZE)
            if url is not None
            else None
        )
        self.icon.update(pixels or self._placeholder_icon or "")

    def _icon_ready(self, row: ResultRow) -> bool:
        if row.name in self._icon_urls:
            url = self._icon_urls[row.name]
            return url is None or self.icons.has_pixels(url, PREVIEW_ICON_SIZE)
        return row.icon_url is not None and self.icons.has_pixels(
            row.icon_url, PREVIEW_ICON_SIZE
        )

    def _prefetch_batch(self, start: int) -> None:
        """Prefetch up to ten rows starting at ``start``."""
        count = 0
        for index in range(start, start + MAX_ICON_FETCHES):
            row = self.results.row_at(index)
            if row is None:
                break
            self._request_icon(row)
            count += 1
        self._prefetch_cursor = max(self._prefetch_cursor, start + count)

    def _request_icon(self, row: ResultRow) -> None:
        if not row.name or row.name in self._icon_pending:
            return
        if row.name in self._icon_urls and self._icon_urls[row.name] is None:
            return
        url = row.icon_url or self._icon_urls.get(row.name)
        if url is not None and self.icons.has_pixels(url, PREVIEW_ICON_SIZE):
            return
        self._icon_pending.add(row.name)
        task = asyncio.create_task(self._load_row_icon(row))
        self._icon_tasks.add(task)
        task.add_done_callback(self._icon_tasks.discard)

    async def _load_row_icon(self, row: ResultRow) -> None:
        try:
            async with self._icon_semaphore:
                url = row.icon_url or self._icon_urls.get(row.name)
                if url is None:
                    url = await self._resolve_icon_url(row.name)
                self._icon_urls[row.name] = url
                if url is not None:
                    await self.icons.get_pixels(url, PREVIEW_ICON_SIZE)
        finally:
            self._icon_pending.discard(row.name)
        if self.is_mounted:
            self.call_later(self._notify_icon_loaded, row.name)

    async def _resolve_icon_url(self, name: str) -> str | None:
        try:
            info = await self.client.store.get_snap_info(
                snap_name=name, fields=["media"]
            )
        except Exception:
            return None
        snap = getattr(info, "snap", None)
        for item in (getattr(snap, "media", None) or []) if snap else []:
            if item.type == "icon":
                return str(item.url)
        return None

    def _notify_icon_loaded(self, name: str) -> None:
        if not self.is_mounted:
            return
        row = self.results.current_row()
        if row is not None and row.name == name:
            self._show_preview_icon(row)

    async def on_unmount(self) -> None:
        tasks = tuple(self._icon_tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.icons.close()
        await close_client(self.client)

    # ------------------------------------------------------------------ state
    def _browse_label(self) -> str:
        if self.mode is BrowseMode.CATEGORY:
            return self.category.replace("-", " ").title()
        if self.mode is BrowseMode.SEARCH:
            request = self.search_request
            if request is None:
                return "Search"
            query = request.query.strip()
            filters = request.filters.summary()
            if query and filters:
                return f'Search: "{query}" ({filters})'
            if query:
                return f'Search: "{query}"'
            return f"Search: {filters}" if filters else "Search"
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
        if mode is not BrowseMode.SEARCH:
            self._search_has_more = False
        self.update_title()
        return self._generation

    def _empty_message(self) -> str:
        return "No results"

    def _apply_rows(self, rows: list[ResultRow], *, append: bool = False) -> None:
        count = (
            self.results.append_rows(rows) if append else self.results.set_rows(rows)
        )
        self.empty_state.update(self._empty_message())
        self.empty_state.display = count == 0
        if append:
            self._prefetch_batch(self._prefetch_cursor)
        else:
            self._prefetch_cursor = 0
            self._prefetch_batch(0)
        self._refresh_preview()
        self._apply_layout()

    def show_error(self, error: BaseException | str | object, title: str) -> None:
        """Surface an error, updating an existing error screen if one is open."""
        current = self.screen
        if isinstance(current, ErrorScreen):
            current.set_error(error, title)
            return
        self.push_screen(ErrorScreen(error, title))

    # ------------------------------------------------------------------ startup
    async def _probe_snapd(self) -> bool:
        self.snapd_available = await client_available(self.client)
        return self.snapd_available

    async def _startup(self) -> None:
        generation = self._generation
        self.results.loading = True
        categories, featured, _available = await asyncio.gather(
            self.client.store.get_categories(),
            self.client.store.find(category=FEATURED_CATEGORY, fields=SEARCH_FIELDS),
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
            self._apply_rows(rows_from_response(featured))
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
        self._apply_rows(rows_from_response(response))

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
            self.client.store.find(category=category, fields=SEARCH_FIELDS),
            "Error - loading category",
        )

    def action_search_snaps(self) -> None:
        self.run_worker(
            self._search_snaps(), group="search-dialog", name="search-dialog"
        )

    async def _search_snaps(self) -> None:
        request = await self.push_screen(
            SearchScreen(
                self.categories,
                initial=self.search_request,
                on_change=self._preview_search,
            ),
            wait_for_dismiss=True,
        )
        if not isinstance(request, SearchRequest) or request.is_empty:
            return
        # Live previews usually already applied this request. If the user hit
        # Enter before the debounce fired, start it now.
        self._preview_search(request)

    def _preview_search(self, request: SearchRequest) -> None:
        """Apply a search request as the form changes, without dismissing it."""
        if request.is_empty:
            return
        if self.mode is BrowseMode.SEARCH and request == self.search_request:
            return

        self.search_request = request
        self.search_page = 1
        self._search_has_more = False
        generation = self._begin_browse(BrowseMode.SEARCH, query=request.query.strip())
        self.run_worker(
            self._run_search(request, generation),
            group="search-preview",
            name="search-preview",
            exclusive=True,
        )

    async def _run_search(self, request: SearchRequest, generation: int) -> None:
        if request.filters.advanced:
            await self._load_rows(
                generation,
                self.client.store.find(
                    query=request.query.strip() or None,
                    fields=SEARCH_FIELDS,
                    **request.filters.find_kwargs(),
                ),
                "Error - searching snaps",
            )
            return
        await self._load_paginated(generation, request=request, page=1)

    async def _load_paginated(
        self, generation: int, request: SearchRequest, *, page: int
    ) -> None:
        self.results.loading = True
        try:
            response = await self.client.store.get_snap_search_paginated(
                q=request.query.strip(),
                arch=paginated_arch(request.filters),
                page=page,
                limit=SEARCH_PAGE_SIZE,
                confinement=paginated_confinement(request.filters),
            )
        except Exception as error:
            if generation == self._generation:
                self.show_error(error, "Error - searching snaps")
            return
        finally:
            if generation == self._generation:
                self.results.loading = False
        if generation != self._generation:
            return

        rows = rows_from_paginated_response(response)
        self.search_page = page
        # PaginatedResponse.has_more assumes 0-based pages; this endpoint is
        # 1-based, so compute the boundary from the total ourselves.
        self._search_has_more = getattr(response, "total", 0) > page * SEARCH_PAGE_SIZE
        self._apply_rows(rows, append=page > 1)
        if self.results.row_count:
            self.results.focus()

    def action_load_more(self) -> None:
        if (
            self.mode is not BrowseMode.SEARCH
            or not self._search_has_more
            or self._loading_more
        ):
            return
        self._loading_more = True
        self.run_worker(
            self._load_more(), group="search-more", name="search-more", exclusive=True
        )

    async def _load_more(self) -> None:
        try:
            request = self.search_request
            if request is None:
                return
            generation = self._generation
            await self._load_paginated(
                generation, request=request, page=self.search_page + 1
            )
        finally:
            self._loading_more = False

    # ------------------------------------------------------------------ management
    def action_show_installed(self) -> None:
        self.push_screen(InstalledScreen(client=self.client))

    def action_show_activity(self) -> None:
        self.push_screen(ActivityScreen(client=self.client))

    # ------------------------------------------------------------------ snap details
    async def _installed_state(self, snap_name: str) -> InstalledState:
        if not self.snapd_available and not await self._probe_snapd():
            return InstalledState(installed=False, error="snapd API not available")
        return await get_installed_state(self.client, snap_name)

    async def open_snap(
        self,
        snap_name: str,
        *,
        install_state: InstalledState | None = None,
        wait_for_dismiss: bool = False,
    ) -> None:
        if not snap_name:
            return
        self.results.loading = True
        try:
            if install_state is None:
                snap_info, install_state = await asyncio.gather(
                    self.client.store.retry_get_snap_info(
                        snap_name=snap_name, fields=VALID_SNAP_INFO_FIELDS
                    ),
                    self._installed_state(snap_name),
                )
            else:
                snap_info = await self.client.store.retry_get_snap_info(
                    snap_name=snap_name, fields=VALID_SNAP_INFO_FIELDS
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
        screen = SnapScreen(
            snap_name=snap_name,
            snap_info=snap_info,
            install_state=install_state,
            client=self.client,
            icon_cache=self.icons,
        )
        if wait_for_dismiss:
            await self.push_screen(screen, wait_for_dismiss=True)
            return
        self.push_screen(screen)

    @on(DataTable.RowHighlighted, "#results-table")
    def _preview_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table is not self.results:
            return
        self._refresh_preview()

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
