import logging
from pathlib import Path

import requests.exceptions
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, Input

from store_tui.api.snaps import SnapsAPI
from store_tui.elements.category_modal import CategoryModal
from store_tui.elements.position_count import PositionCount
from store_tui.elements.search_modal import SnapSearchModal
from store_tui.elements.snap_modal import SnapModal
from store_tui.schemas.snaps.categories import CategoryResponse
from store_tui.schemas.snaps.search import SearchResponse

logger = logging.getLogger(__name__)

snaps_api = SnapsAPI(
    base_url="https://api.snapcraft.io",
    version="v2",
    headers={"Snap-Device-Series": "16", "X-Ubuntu-Series": "16"},
)
ConnectionError
TABLE_COLUMNS = ("Name", "Description")


def get_top_snaps_from_category(api: SnapsAPI, category: str) -> SearchResponse:
    return api.find(category=category, fields=["title", "store-url", "summary"])


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
        self.data_table = DataTable()

        self.update_title()
        self.table_position_count = PositionCount(id="table-position-count")
        self.setup_data_table()

    def setup_data_table(self):
        self.data_table.add_columns(*TABLE_COLUMNS)
        for column in self.data_table.columns.values():
            column.auto_width = True
        self.data_table.cursor_type = "row"

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
        self.update_table(top_snaps=top_snaps)
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
        self.update_table(top_snaps=top_snaps)
        self.update_title()

    def update_title(self):
        """Set title based on the current category"""
        self.title = f"SnapStoreTUI - {self.current_category.capitalize()}"

    def update_table(self, top_snaps: SearchResponse):
        self.data_table.clear()
        self.table_position_count.total = 0
        self.table_position_count.current_number = 0
        self.data_table.set_loading(True)

        self.table_position_count.total = len(top_snaps.results)
        self.table_position_count.current_number = 0
        for snap_result in top_snaps.results:
            self.data_table.add_row(
                snap_result.snap.title,
                snap_result.snap.summary,
                key=snap_result.name,
            )
        self.data_table.set_loading(False)

    def on_data_table_row_highlighted(self, row_highlighted: DataTable.RowHighlighted):
        self.table_position_count.current_number = (
            self.data_table.get_row_index(row_highlighted.row_key) + 1
        )

    def on_data_table_row_selected(self, row_selected: DataTable.RowSelected):
        snap_row_key = row_selected.row_key.value
        print(snap_row_key)
        snap_modal = SnapModal(snap_name=snap_row_key, api=snaps_api)
        self.push_screen(snap_modal)

    def on_mount(self):
        try:
            categories_response = snaps_api.get_categories()
            self.all_categories: list[str] = [
                category.name for category in categories_response.categories
            ]
            top_snaps = get_top_snaps_from_category(snaps_api, self.current_category)
        except requests.exceptions.ConnectionError:
            logger.exception("Error getting categories or top snaps")
            categories_response = CategoryResponse(categories=[])
            self.all_categories = []
            top_snaps = SearchResponse(results=[])
            pass
        self.update_table(top_snaps=top_snaps)


if __name__ == "__main__":
    SnapStoreTUI().run()
