"""Result table and the position counter shown in the footer."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from snap_python.schemas.store.search import SearchResponse
from textual import on
from textual.widgets import DataTable, Label

TABLE_COLUMNS = ("Name", "Version", "Description")


@dataclass(frozen=True)
class ResultRow:
    name: str
    summary: str = ""
    version: str = ""


def rows_from_search_response(
    response: SearchResponse | None,
) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for result in response.results if response is not None else []:
        if not result.name:
            continue
        summary = ""
        if result.snap is not None and result.snap.summary:
            summary = str(result.snap.summary)
        version = ""
        if result.revision is not None and result.revision.version:
            version = str(result.revision.version)
        rows.append(ResultRow(name=result.name, summary=summary, version=version))
    return rows


class PositionCount(Label):
    """Displays ``current/total`` for the highlighted table row."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__("0/0", *args, **kwargs)
        self._current = 0
        self._total = 0

    def set_position(self, current: int, total: int) -> None:
        self._current = max(current, 0)
        self._total = max(total, 0)
        self.update(f"{self._current}/{self._total}")


class ResultsTable(DataTable):
    """DataTable that a caller fills with an already-awaited list of rows."""

    def __init__(
        self,
        position_count: PositionCount | None = None,
        *,
        columns: tuple[str, ...] = TABLE_COLUMNS,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._table_columns = tuple(columns)
        self._position_count = position_count
        self._row_names: set[str] = set()

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        self.add_columns(*self._table_columns)
        for column in self.columns.values():
            column.auto_width = True

    def set_rows(self, rows: Iterable[ResultRow] | None) -> int:
        """Replace the table contents synchronously and return the row count."""
        self.clear(columns=False)
        self._row_names = set()
        self._add_unique(rows)
        self._sync_position(len(self._row_names))
        return len(self._row_names)

    def append_rows(self, rows: Iterable[ResultRow] | None) -> int:
        """Append unseen rows and return the total number of rows."""
        self._add_unique(rows)
        self._sync_position(len(self._row_names))
        return len(self._row_names)

    def _add_unique(self, rows: Iterable[ResultRow] | None) -> None:
        for row in rows or []:
            if not row.name or row.name in self._row_names:
                continue
            self._row_names.add(row.name)
            self.add_row(row.name, row.version, row.summary, key=row.name)

    def _sync_position(self, total: int) -> None:
        if self._position_count is None:
            return
        current = min(self.cursor_row, total - 1) + 1 if total else 0
        self._position_count.set_position(current, total)

    @on(DataTable.RowHighlighted)
    def _track_highlight(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table is not self or self._position_count is None:
            return
        if not self.row_count:
            self._position_count.set_position(0, 0)
            return
        self._position_count.set_position(
            event.data_table.cursor_row + 1, self.row_count
        )
