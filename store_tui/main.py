import asyncio
import logging
from pathlib import Path

from snap_python.client import SnapClient
from snap_python.schemas.store.categories import CategoryResponse
from snap_python.schemas.store.info import VALID_SNAP_INFO_FIELDS
from snap_python.schemas.store.search import SearchResponse
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, Input

from store_tui.elements.category_modal import CategoryModal
from store_tui.elements.error_modal import ErrorModal
from store_tui.elements.position_count import PositionCount
from store_tui.elements.search_modal import SnapSearchModal
from store_tui.elements.snap_modal import SnapModal
from store_tui.elements.snap_result_table import SnapResultTable

logger = logging.getLogger(__name__)

snaps_api = SnapClient(
    store_base_url="https://api.snapcraft.io",
    version="v2",
    store_headers={"Snap-Device-Series": "16", "X-Ubuntu-Series": "16"},
)
ConnectionError
TABLE_COLUMNS = ("Name", "Description")


class SnapStoreTUI(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "choose_category", "Category"),
        ("s", "search_snaps", "Search"),
    ]
    CSS_PATH = Path(__file__).parent / "styles" / "main.tcss"

    def __init__(self, api: SnapClient) -> None:
        super().__init__()
        self.current_category = "featured"
        self.all_categories = []
        self.api = api

        self.update_title()
        self.table_position_count = PositionCount(id="table-position-count")
        self.data_table = SnapResultTable(
            table_position_count=self.table_position_count, table_columns=TABLE_COLUMNS
        )
        self.header = Header()
        self.header.tall = False
        self.snapd_api_available = False

    def compose(self) -> ComposeResult:
        yield self.header
        yield self.data_table
        with Horizontal(id="footer-outer"):
            with Horizontal(id="footer-inner"):
                yield Footer(show_command_palette=False)
            yield self.table_position_count

    async def action_quit(self):
        self.exit()

    @work
    async def action_choose_category(self):
        self.current_category = await self.push_screen(
            CategoryModal(
                categories=self.all_categories,
                current_category=self.current_category,
            ),
            wait_for_dismiss=True,
        )
        top_snaps = self.api.store.get_top_snaps_from_category(self.current_category)
        await self.data_table.update_table(top_snaps=top_snaps)
        self.update_title()

    @work
    async def action_search_snaps(self):
        # open modal
        # get search query
        search_query: Input.Submitted = await self.push_screen(
            SnapSearchModal(), wait_for_dismiss=True
        )
        self.current_category = "Search"
        # send to update table to use "find" method
        top_snaps = self.api.store.find(
            query=search_query.value, fields=["title", "store-url", "summary"]
        )
        await self.data_table.update_table(top_snaps=top_snaps)
        self.update_title()

    def update_title(self):
        """Set title based on the current category"""
        self.title = f"store-tui - {self.current_category.capitalize()}"

    async def on_mount(self):
        self.data_table.loading = True
        self.call_after_refresh(self.init_main_screen)

        # check snapd api access
        try:
            await self.api.ping()
            self.snapd_api_available = True
        except Exception as e:
            self.snapd_api_available = False

    async def init_main_screen(self):
        try:
            categories_response = await self.api.store.get_categories()
            self.all_categories: list[str] = [
                category.name for category in categories_response.categories
            ]
            top_snaps = self.api.store.get_top_snaps_from_category(
                self.current_category
            )
        except Exception as e:
            logger.exception("Error getting categories or top snaps")
            categories_response = CategoryResponse(categories=[])
            self.all_categories = ["featured"]
            top_snaps = SearchResponse(results=[])
            self.push_screen(
                ErrorModal(e, error_title="Error - getting categories or top snaps")
            )
        finally:
            self.data_table.loading = False
        await self.data_table.update_table(top_snaps=top_snaps)
        if self.data_table.row_count > 0:
            self.data_table.focus()

    @on(DataTable.RowSelected)
    async def on_data_table_row_selected(self, row_selected: DataTable.RowSelected):
        snap_row_key = row_selected.row_key.value
        try:
            self.data_table.loading = True
            if self.snapd_api_available:
                snap_install_data = self.api.snaps.get_snap_info(snap_row_key)
            else:
                # empty await
                snap_install_data = asyncio.sleep(0)
            snap_info = self.api.store.retry_get_snap_info(
                snap_name=snap_row_key, fields=VALID_SNAP_INFO_FIELDS
            )
            snap_install_data, snap_info = await asyncio.gather(
                snap_install_data, snap_info
            )
        except Exception as e:
            self.push_screen(ErrorModal(e, error_title="Error - retrieving snap info"))
            snap_info = None
            snap_install_data = None
        finally:
            self.data_table.loading = False

        if snap_info is None:
            return
        snap_modal = SnapModal(
            snap_name=snap_row_key,
            api=self.api,
            snap_info=snap_info,
            snap_install_data=snap_install_data,
        )
        self.push_screen(snap_modal)


if __name__ == "__main__":
    SnapStoreTUI(api=snaps_api).run()
