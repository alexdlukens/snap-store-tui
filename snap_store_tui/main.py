from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header

from snap_store_tui.api.snaps import SnapsAPI
from snap_store_tui.elements.category_modal import CategoryModal

snaps_api = SnapsAPI(
    base_url="https://api.snapcraft.io",
    version="v2",
    headers={"Snap-Device-Series": "16"},
)

TABLE_COLUMNS = ("#", "Name", "Description")


def get_top_snaps_from_category(api: SnapsAPI, category: str):
    return api.find(category=category, fields=["title", "store-url", "summary"])


class SnapStoreTUI(App):
    current_category = "featured"
    BINDINGS = [("q", "quit", "Quit"), ("c", "choose_category", "Category")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable()
        yield Footer()

    async def action_quit(self):
        self.exit()

    async def get_updated_category(self):
        self.current_category = await self.push_screen(
            CategoryModal(
                categories=["featured", "games", "productivity", "social", "utilities"]
            ),
            wait_for_dismiss=True,
        )
        self.update_table()

    async def action_choose_category(self):
        # setup category modal here
        self.run_worker(self.get_updated_category)

    def update_table(self):
        table = self.query_one(DataTable)
        table.clear()
        table.add_columns(*TABLE_COLUMNS)
        top_snaps = get_top_snaps_from_category(snaps_api, self.current_category)
        for i, snap_result in enumerate(top_snaps.results):
            table.add_row(str(i), snap_result.snap.title, snap_result.snap.summary)

    def on_mount(self):
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        self.update_table()


if __name__ == "__main__":
    SnapStoreTUI().run()
