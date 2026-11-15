"""Result table and the position counter shown in the footer."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from rich.cells import cell_len
from snap_python.schemas.store.search import SearchResponse
from textual import on
from textual.widgets import DataTable, Label

TABLE_COLUMNS = ("Name", "Version", "Description")
MIN_SUMMARY_WIDTH = 32


@dataclass(frozen=True)
class ResultRow:
    name: str
    summary: str = ""
    version: str = ""
    title: str = ""
    publisher: str = ""
    revision: int | str | None = None
    channel: str | None = None
    confinement: str | None = None
    base: str | None = None
    type: str | None = None
    store_url: str | None = None
    icon_url: str | None = None


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def rows_from_search_response(
    response: SearchResponse | None,
) -> list[ResultRow]:
    rows: list[ResultRow] = []
    for result in response.results if response is not None else []:
        if not result.name:
            continue
        snap = result.snap
        revision = result.revision
        publisher = ""
        icon_url = None
        if snap is not None and snap.publisher is not None:
            publisher = str(snap.publisher.display_name or "")
        for item in (snap.media or []) if snap is not None else []:
            if item.type == "icon":
                icon_url = _optional_text(item.url)
                break
        rows.append(
            ResultRow(
                name=result.name,
                summary=str(snap.summary or "") if snap is not None else "",
                version=(_optional_text(revision.version) or "") if revision else "",
                title=str(snap.title or "") if snap is not None else "",
                publisher=publisher,
                revision=revision.revision if revision else None,
                channel=_optional_text(revision.channel) if revision else None,
                confinement=(
                    _optional_text(revision.confinement) if revision else None
                ),
                base=_optional_text(revision.base) if revision else None,
                type=_optional_text(revision.type) if revision else None,
                store_url=_optional_text(snap.store_url) if snap is not None else None,
                icon_url=icon_url,
            )
        )
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
        self._rows_by_name: dict[str, ResultRow] = {}
        self._summary_width = MIN_SUMMARY_WIDTH
        self._description_key = None

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.zebra_stripes = True
        keys = self.add_columns(*self._table_columns)
        self._description_key = keys[2] if len(keys) > 2 else None
        for column in self.columns.values():
            column.auto_width = True
        if self._description_key is not None:
            description = self.columns[self._description_key]
            description.auto_width = False
            description.width = self._summary_width

    def set_rows(self, rows: Iterable[ResultRow] | None) -> int:
        """Replace the table contents synchronously and return the row count."""
        self.clear(columns=False)
        for column in self.columns.values():
            column.content_width = cell_len(column.label.plain)
        self._rows_by_name = {}
        self._add_unique(rows)
        self._sync_position(len(self._rows_by_name))
        return len(self._rows_by_name)

    def append_rows(self, rows: Iterable[ResultRow] | None) -> int:
        """Append unseen rows and return the total number of rows."""
        self._add_unique(rows)
        self._sync_position(len(self._rows_by_name))
        return len(self._rows_by_name)

    def current_row(self) -> ResultRow | None:
        if not self._rows_by_name or not self.row_count:
            return None
        index = max(0, min(self.cursor_row, self.row_count - 1))
        row_key = self.ordered_rows[index].key
        return self._rows_by_name.get(str(row_key.value))

    def _column_widths(self) -> tuple[int, int]:
        name = cell_len("Name")
        version = cell_len("Version")
        for row in self._rows_by_name.values():
            name = max(name, cell_len(row.name))
            version = max(version, cell_len(row.version))
        return name, version

    def _render_width(self, name: int, version: int, summary: int) -> int:
        padding = 3 * 2 * self.cell_padding
        return name + version + summary + padding

    def min_content_width(self) -> int:
        name, version = self._column_widths()
        return self._render_width(name, version, MIN_SUMMARY_WIDTH)

    def summary_width_for(self, pane_width: int) -> int:
        """Use all leftover table space for the wrapped description."""
        name, version = self._column_widths()
        available = pane_width - (name + version + 3 * 2 * self.cell_padding)
        return max(MIN_SUMMARY_WIDTH, available)

    def set_summary_width(self, width: int) -> None:
        if width == self._summary_width:
            return
        self._summary_width = width
        if self._description_key is None:
            return
        description = self.columns[self._description_key]
        description.auto_width = False
        description.width = width
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        """Re-wrap descriptions after the available table width changes."""
        selected = self.current_row()
        selected_name = selected.name if selected is not None else None
        scroll_y = self.scroll_y
        self.clear(columns=False)
        for column in self.columns.values():
            column.content_width = cell_len(column.label.plain)
        for row in self._rows_by_name.values():
            self._add_row(row)
        names = list(self._rows_by_name)
        if selected_name in self._rows_by_name:
            self.move_cursor(row=names.index(selected_name))
        self.call_after_refresh(self._restore_scroll, scroll_y)
        self._sync_position(len(names))

    def _restore_scroll(self, scroll_y: float) -> None:
        if self.is_mounted:
            self.scroll_y = min(scroll_y, self.max_scroll_y)

    def _add_row(self, row: ResultRow) -> None:
        self.add_row(
            row.name,
            row.version,
            row.summary,
            key=row.name,
            height=None,
        )

    def _add_unique(self, rows: Iterable[ResultRow] | None) -> None:
        for row in rows or []:
            if not row.name or row.name in self._rows_by_name:
                continue
            self._rows_by_name[row.name] = row
            self._add_row(row)

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
