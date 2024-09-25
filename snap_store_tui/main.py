from pathlib import Path

import requests.exceptions
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header

from snap_store_tui.api.snaps import SnapsAPI
from snap_store_tui.elements.category_modal import CategoryModal
from snap_store_tui.elements.position_count import PositionCount
from snap_store_tui.elements.snap_modal import SnapModal
from snap_store_tui.schemas.snaps.search import SearchResponse

snaps_api = SnapsAPI(
    base_url="https://api.snapcraft.io",
    version="v2",
    headers={"Snap-Device-Series": "16"},
)
ConnectionError
TABLE_COLUMNS = ("#", "Name", "Description")


def get_top_snaps_from_category(api: SnapsAPI, category: str) -> SearchResponse:
    return api.find(category=category, fields=["title", "store-url", "summary"])


class SnapStoreTUI(App):
    current_category = "featured"
    BINDINGS = [("q", "quit", "Quit"), ("c", "choose_category", "Category")]
    CSS_PATH = Path(__file__).parent / "styles" / "main.tcss"

    def __init__(self) -> None:
        super().__init__()
        self.all_categories = []
        try:
            categories_response = snaps_api.get_categories()
            self.all_categories: list[str] = [
                category.name for category in categories_response.categories
            ]
        except requests.exceptions.ConnectionError:
            # todo: show network error modal
            pass
        self.update_title()
        self.table_position_count = PositionCount(id="table-position-count")

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable()
        with Horizontal(id="footer-outer"):
            with Horizontal(id="footer-inner"):
                yield Footer(show_command_palette=False)
            yield self.table_position_count

    async def action_quit(self):
        self.exit()

    @work
    async def get_updated_category(self):
        self.current_category = await self.push_screen(
            CategoryModal(
                categories=self.all_categories,
                current_category=self.current_category,
            ),
            wait_for_dismiss=True,
        )
        self.update_table()
        self.update_title()

    async def action_choose_category(self):
        # setup category modal here
        self.get_updated_category()

    def update_title(self):
        self.title = f"SnapStoreTUI - {self.current_category.capitalize()}"

    def update_table(self):
        table = self.query_one(DataTable)
        table.clear()
        self.table_position_count.total = 0
        self.table_position_count.current_number = 0
        table.set_loading(True)
        table.add_columns(*TABLE_COLUMNS)
        for column in table.columns:
            table.columns[column].auto_width = True
        # TODO: Handle errors when getting top snaps for category
        try:
            top_snaps = get_top_snaps_from_category(snaps_api, self.current_category)
        except requests.exceptions.ConnectionError:
            top_snaps = SearchResponse(results=[])
            pass
        self.table_position_count.total = len(top_snaps.results)
        self.table_position_count.current_number = 0
        for i, snap_result in enumerate(top_snaps.results):
            table.add_row(str(i), snap_result.snap.title, snap_result.snap.summary)
        table.set_loading(False)

    def on_data_table_row_highlighted(self, row_highlighted: DataTable.RowHighlighted):
        table = self.query_one(DataTable)
        self.table_position_count.current_number = table.get_row_index(
            row_highlighted.row_key
        )

    def on_mount(self):
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        self.update_table()


if __name__ == "__main__":
    SnapStoreTUI().run()
