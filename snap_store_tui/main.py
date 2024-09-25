from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header

from snap_store_tui.api.snaps import SnapsAPI
from snap_store_tui.elements.category_modal import CategoryModal
from snap_store_tui.schemas.snaps.categories import CategoryResponse

snaps_api = SnapsAPI(
    base_url="https://api.snapcraft.io",
    version="v2",
    headers={"Snap-Device-Series": "16"},
)

TABLE_COLUMNS = ("#", "Name", "Description")

all_categories = snaps_api.get_categories()
all_categories: list[str] = [category.name for category in all_categories.categories]


def get_top_snaps_from_category(api: SnapsAPI, category: str):
    return api.find(category=category, fields=["title", "store-url", "summary"])


class SnapStoreTUI(App):
    current_category = "featured"
    BINDINGS = [("q", "quit", "Quit"), ("c", "choose_category", "Category")]

    def __init__(self) -> None:
        super().__init__()
        self.update_title()

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable()
        yield Footer()

    async def action_quit(self):
        self.exit()

    async def get_updated_category(self):
        self.current_category = await self.push_screen(
            CategoryModal(
                categories=all_categories,
                current_category=self.current_category,
            ),
            wait_for_dismiss=True,
        )
        self.update_table()
        self.update_title()

    async def action_choose_category(self):
        # setup category modal here
        self.run_worker(self.get_updated_category)

    def update_title(self):
        self.title = f"SnapStoreTUI - {self.current_category.capitalize()}"

    def update_table(self):
        table = self.query_one(DataTable)
        table.clear()
        table.add_columns(*TABLE_COLUMNS)
        for column in table.columns:
            table.columns[column].auto_width = True
        top_snaps = get_top_snaps_from_category(snaps_api, self.current_category)
        for i, snap_result in enumerate(top_snaps.results):
            table.add_row(str(i), snap_result.snap.title, snap_result.snap.summary)

    def on_mount(self):
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        self.update_table()


if __name__ == "__main__":
    SnapStoreTUI().run()
