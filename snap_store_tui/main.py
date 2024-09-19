from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header

from snap_store_tui.api.snaps import SnapsAPI

snaps_api = SnapsAPI(
    base_url="https://api.snapcraft.io",
    version="v2",
    headers={"Snap-Device-Series": "16"},
)

TABLE_COLUMNS = ("#", "Name", "Description")

current_category = "featured"


def get_top_snaps_from_category(api: SnapsAPI, category: str):
    return api.find(category=category, fields=["title", "store-url", "summary"])


class SnapStoreTUI(App):
    BINDINGS = [("q", "quit", "Quit"), ("c", "change_category", "Category")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable()
        yield Footer()

    async def action_quit(self):
        self.exit()

    async def action_choose_category(self):
        pass

    def update_table(self):
        table = self.query_one(DataTable)
        table.clear()
        table.add_columns(*TABLE_COLUMNS)
        top_snaps = get_top_snaps_from_category(snaps_api, current_category)
        for i, snap_result in enumerate(top_snaps.results):
            table.add_row(str(i), snap_result.snap.title, snap_result.snap.summary)

    def on_mount(self):
        table = self.query_one(DataTable)
        table.cursor_type = "row"
        self.update_table()


if __name__ == "__main__":
    SnapStoreTUI().run()
