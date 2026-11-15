"""snapd change list with progress and abort support."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.coordinate import Coordinate
from textual.screen import ModalScreen
from textual.widgets import DataTable, Footer, Label

from store_tui.errors import snapd_error_hint
from store_tui.screens.confirm import ConfirmScreen

ACTIVITY_TITLE = "Snapd activity"
LOAD_ERROR_TITLE = "Error - loading snapd activity"


def progress_label(change: Any) -> str:
    """Format ``done/total`` for a change, or ``-`` without a positive total."""
    overall = getattr(change, "overall_progress", None)
    done = getattr(overall, "done", 0)
    total = getattr(overall, "total", 0)
    if isinstance(total, int) and total > 0:
        return f"{done}/{total}"
    return "-"


class ActivityScreen(ModalScreen[None]):
    """Browse snapd changes and abort the selected one."""

    BINDINGS = [
        ("escape", "dismiss_screen", "Close"),
        ("q", "dismiss_screen", "Close"),
        ("r", "refresh", "Refresh"),
        ("a", "abort_selected", "Abort"),
    ]

    DEFAULT_CSS = """
    ActivityScreen {
        align: center middle;
    }

    #activity-container {
        width: 90%;
        height: 80%;
        padding: 1 2;
        border: round $border;
        background: $panel;
    }

    #activity-title {
        width: 100%;
        height: 1;
        content-align: center middle;
        text-style: bold;
        padding-bottom: 1;
    }

    #activity-table {
        height: 1fr;
    }

    #activity-empty {
        width: 100%;
        height: auto;
        padding: 1 0;
        text-align: center;
        color: $text-muted;
    }

    #activity-status {
        width: 100%;
        height: auto;
        padding: 0 0 1 0;
        color: $text-muted;
    }
    """

    def __init__(self, client: Any) -> None:
        super().__init__()
        self.client = client
        self.changes: dict[str, Any] = {}

        self.table = DataTable(id="activity-table")
        self.table.add_columns("Summary", "Kind", "Status", "Progress")
        self.empty_label = Label("No changes", id="activity-empty")
        self.status_label = Label("", id="activity-status")

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(ACTIVITY_TITLE, id="activity-title"),
            self.table,
            self.empty_label,
            self.status_label,
            id="activity-container",
        )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.table.focus()
        self._start_refresh()

    # ------------------------------------------------------------------ loading
    def _start_refresh(self) -> None:
        self.run_worker(
            self.refresh_changes(),
            group="activity",
            name="activity-changes",
            exclusive=True,
        )

    def action_refresh(self) -> None:
        self.status_label.update("")
        self._start_refresh()

    async def refresh_changes(self) -> None:
        """Reload every change from snapd and rebuild the table."""
        if self.client is None:
            self.status_label.update("snapd is unavailable")
            return
        try:
            response = await self.client.changes.list_changes(select="all")
        except Exception as error:
            self._report_error(error)
            return

        result = getattr(response, "changes", None) or []
        changes = [change for change in result if getattr(change, "id", None)]
        self.changes = {str(change.id): change for change in changes}

        self.table.clear()
        for change in changes:
            self.table.add_row(
                str(getattr(change, "summary", "")),
                str(getattr(change, "kind", "")),
                str(getattr(change, "status", "")),
                progress_label(change),
                key=str(change.id),
            )
        self.empty_label.display = not changes
        if changes and self.is_mounted:
            self.table.focus()

    def _report_error(self, error: BaseException) -> None:
        show_error = getattr(self.app, "show_error", None)
        if callable(show_error):
            show_error(error, LOAD_ERROR_TITLE)
            return
        hint = snapd_error_hint(error)
        message = hint or str(error)
        self.status_label.update(f"{LOAD_ERROR_TITLE}: {message}")

    # ------------------------------------------------------------------ aborting
    def _selected_change(self) -> Any | None:
        if not self.table.row_count:
            return None
        row = self.table.cursor_row
        if row < 0 or row >= self.table.row_count:
            return None
        cell_key = self.table.coordinate_to_cell_key(Coordinate(row, 0))
        return self.changes.get(str(cell_key.row_key.value))

    def action_abort_selected(self) -> None:
        change = self._selected_change()
        if change is None:
            self.notify("Select a change to abort", severity="warning", timeout=3)
            return
        if getattr(change, "ready", False):
            self.notify("Change already finished", severity="warning", timeout=3)
            return
        if self.client is None:
            self.notify("snapd is unavailable", severity="warning", timeout=3)
            return
        change_id = str(change.id)
        summary = str(getattr(change, "summary", change_id))
        self.app.push_screen(
            ConfirmScreen(
                "Abort change?",
                f"Abort {summary!r} while it is still running?",
                confirm_label="Abort",
            ),
            callback=lambda confirmed: self._abort_confirmed(confirmed, change_id),
        )

    def _abort_confirmed(self, confirmed: bool | None, change_id: str) -> None:
        if confirmed is not True or not self.is_mounted or self.client is None:
            return
        self.status_label.update("Aborting…")
        self.run_worker(
            self._abort(change_id),
            group="activity-abort",
            name="activity-abort",
            exclusive=True,
        )

    async def _abort(self, change_id: str) -> None:
        self.status_label.update("Aborting…")
        try:
            await self.client.changes.abort(change_id)
        except Exception as error:
            # Aborting is a user action; keep the activity list visible and
            # report the failure inline instead of replacing it with an error screen.
            message = snapd_error_hint(error) or str(error)
            self.status_label.update(f"Abort failed: {message}")
            self.notify(
                f"Could not abort change {change_id}: {message}",
                severity="error",
                timeout=5,
            )
            return
        await self.refresh_changes()

    # ------------------------------------------------------------------ closing
    def action_dismiss_screen(self) -> None:
        self.dismiss(None)
