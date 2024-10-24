from typing import Coroutine

from textual import on
from textual.widgets import DataTable

from store_tui.elements.position_count import PositionCount
from store_tui.schemas.snaps.search import SearchResponse


class SnapResultTable(DataTable):
    def __init__(self, table_position_count: PositionCount, table_columns):
        super().__init__()
        self.table_position_count = table_position_count
        self.add_columns(*table_columns)
        for column in self.columns.values():
            column.auto_width = True
        self.cursor_type = "row"

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
                snap_result.snap.title,
                snap_result.snap.summary,
                key=snap_result.name,
            )
        self.set_loading(False)

    @on(DataTable.RowHighlighted)
    def on_data_table_row_highlighted(self, row_highlighted: DataTable.RowHighlighted):
        self.table_position_count.current_number = (
            self.get_row_index(row_highlighted.row_key) + 1
        )
