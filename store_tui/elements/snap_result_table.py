from pathlib import Path
from typing import Coroutine

from snap_python.schemas.store.search import SearchResponse
from textual import on
from textual.widgets import DataTable
from textual.widgets.data_table import RowDoesNotExist

from store_tui.elements.position_count import PositionCount


class SnapResultTable(DataTable):
    MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "main.tcss"

    def __init__(self, table_position_count: PositionCount, table_columns):
        super().__init__()
        self.table_position_count = table_position_count
        self.table_columns = table_columns

        self.call_after_refresh(self.after_init)

    async def update_table(self, top_snaps: Coroutine[None, None, SearchResponse]):
        self.clear()
        self.table_position_count.total = 0
        self.table_position_count.current_number = 0
        self.set_loading(True)

        # check if top_snaps is a coroutine, if so, await it
        response: SearchResponse = top_snaps
        if isinstance(top_snaps, Coroutine):
            response = await top_snaps

        self.table_position_count.total = len(response.results)
        self.table_position_count.current_number = 0
        for snap_result in response.results:
            self.add_row(
                snap_result.name,
                snap_result.snap.summary,
                key=snap_result.name,
            )
        self.set_loading(False)

    async def after_init(self):
        self.add_columns(*self.table_columns)
        for column in self.columns.values():
            column.auto_width = True
        self.cursor_type = "row"

    @on(DataTable.RowHighlighted)
    def on_data_table_row_highlighted(self, row_highlighted: DataTable.RowHighlighted):
        try:
            self.table_position_count.current_number = (
                self.get_row_index(row_highlighted.row_key) + 1
            )
        except RowDoesNotExist:
            # occurs when unable to load data table / data table empty
            self.table_position_count.current_number = 0
