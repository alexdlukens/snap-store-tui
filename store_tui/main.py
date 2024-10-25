import logging
from pathlib import Path

import retry
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, Input

from store_tui.api.snaps import SnapsAPI
from store_tui.elements.category_modal import CategoryModal
from store_tui.elements.error_modal import ErrorModal
from store_tui.elements.position_count import PositionCount
from store_tui.elements.search_modal import SnapSearchModal
from store_tui.elements.snap_modal import SnapModal
from store_tui.elements.snap_result_table import SnapResultTable
from store_tui.schemas.snaps.categories import CategoryResponse
from store_tui.schemas.snaps.info import VALID_SNAP_INFO_FIELDS
from store_tui.schemas.snaps.search import SearchResponse

logger = logging.getLogger(__name__)

snaps_api = SnapsAPI(
    base_url="https://api.snapcraft.io",
    version="v2",
    headers={"Snap-Device-Series": "16", "X-Ubuntu-Series": "16"},
)
ConnectionError
TABLE_COLUMNS = ("Name", "Description")


async def get_top_snaps_from_category(api: SnapsAPI, category: str) -> SearchResponse:
    return await api.find(category=category, fields=["title", "store-url", "summary"])


@retry.retry(Exception, tries=3, delay=2, backoff=2)
async def retry_get_snap_info(snap_name: str, fields: list[str]):
    return await snaps_api.get_snap_info(snap_name=snap_name, fields=fields)


class SnapStoreTUI(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "choose_category", "Category"),
        ("s", "search_snaps", "Search"),
    ]
    CSS_PATH = Path(__file__).parent / "styles" / "main.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.current_category = "featured"
        self.all_categories = []

        self.update_title()
        self.table_position_count = PositionCount(id="table-position-count")
        self.data_table = SnapResultTable(
            table_position_count=self.table_position_count, table_columns=TABLE_COLUMNS
        )

    def compose(self) -> ComposeResult:
        yield Header()
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
        top_snaps = get_top_snaps_from_category(snaps_api, self.current_category)
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
        top_snaps = snaps_api.find(
            query=search_query.value, fields=["title", "store-url", "summary"]
        )
        await self.data_table.update_table(top_snaps=top_snaps)
        self.update_title()

    def update_title(self):
        """Set title based on the current category"""
        self.title = f"SnapStoreTUI - {self.current_category.capitalize()}"

    async def on_mount(self):
        try:
            self.data_table.loading = True
            categories_response = await snaps_api.get_categories()
            self.all_categories: list[str] = [
                category.name for category in categories_response.categories
            ]
            top_snaps = get_top_snaps_from_category(snaps_api, self.current_category)
        except Exception as e:
            logger.exception("Error getting categories or top snaps")
            categories_response = CategoryResponse(categories=[])
            self.all_categories = []
            top_snaps = SearchResponse(results=[])
            self.push_screen(
                ErrorModal(e, error_title="Error - getting categories or top snaps")
            )
        finally:
            self.data_table.loading = False
        await self.data_table.update_table(top_snaps=top_snaps)

    @on(DataTable.RowSelected)
    async def on_data_table_row_selected(self, row_selected: DataTable.RowSelected):
        snap_row_key = row_selected.row_key.value
        try:
            self.data_table.loading = True
            snap_info = await retry_get_snap_info(
                snap_name=snap_row_key, fields=VALID_SNAP_INFO_FIELDS
            )
        except Exception as e:
            self.push_screen(ErrorModal(e, error_title="Error - retrieving snap info"))
            snap_info = None
        finally:
            self.data_table.loading = False

        if snap_info is None:
            return
        snap_modal = SnapModal(
            snap_name=snap_row_key, api=snaps_api, snap_info=snap_info
        )
        self.push_screen(snap_modal)


if __name__ == "__main__":
    SnapStoreTUI().run()
