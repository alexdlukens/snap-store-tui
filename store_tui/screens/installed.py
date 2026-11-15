"""Installed snaps management: details, refresh, remove, hold, revert, logs."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

import humanize
from rich.cells import cell_len
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DataTable, Footer, Header, Label, Static

from store_tui.changes import progress_of, watch_change
from store_tui.screens.confirm import ConfirmScreen
from store_tui.screens.hold import HoldScreen
from store_tui.screens.logs import LogsScreen
from store_tui.snapd import InstalledSnapRow, list_installed, state_from_row
from store_tui.widgets.progress import ProgressBarWithMessage

CHANGE_TIMEOUT = 300.0
IN_PROGRESS_MESSAGE = "Operation in progress — please wait"
TABLE_COLUMNS = ("Name", "Version", "Channel", "Revision", "Status")
HOLD_DURATIONS = {"1d": 1, "7d": 7, "30d": 30}
MIN_DETAILS_WIDTH = 32


def format_datetime(value: datetime | None) -> str:
    """Render a snapd timestamp consistently for the details pane."""
    if value is None:
        return "none"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def format_size(size: int | None) -> str:
    """Show a human-readable size, keeping the exact byte count."""
    if size is None:
        return "unknown"
    return f"{humanize.naturalsize(size)} ({size:,} bytes)"


def format_refresh_failures(value: Any | None) -> str:
    """Summarise the failed-refresh history snapd reports for a snap."""
    if value is None:
        return "none"
    count = getattr(value, "failure_count", None)
    last = getattr(value, "last_failure_time", None)
    severity = getattr(value, "last_failure_severity", None)
    revision = getattr(value, "revision", None)
    parts: list[str] = []
    if count is not None:
        parts.append(f"{count} failed attempt{'s' if count != 1 else ''}")
    if last is not None:
        parts.append(f"last at {format_datetime(last)}")
    if severity:
        parts.append(f"severity {severity}")
    if revision is not None:
        parts.append(f"revision {revision}")
    return ", ".join(parts) or "reported"


def format_details(row: InstalledSnapRow) -> str:
    """Render every installed-state field the management screen exposes."""
    tracks = ", ".join(row.tracks) if row.tracks else "none"
    components = ", ".join(row.components) if row.components else "none"
    lines = [
        f"Name: {row.name}",
        f"Summary: {row.summary or 'none'}",
        f"Version: {row.version or 'unknown'}",
        f"Revision: {row.revision if row.revision is not None else 'unknown'}",
        f"Channel: {row.channel or 'unknown'}",
        f"Status: {row.status or 'unknown'}",
        f"Size: {format_size(row.size)}",
        f"Installed: {format_datetime(row.install_date)}",
        f"Hold: {'held until ' + format_datetime(row.hold) if row.hold else 'none'}",
        f"Gating hold: {format_datetime(row.gating_hold)}",
        (
            "Refresh inhibit: "
            f"{format_datetime(row.refresh_inhibit) if row.refresh_inhibit else 'none'}"
        ),
        f"Refresh failures: {format_refresh_failures(row.refresh_failures)}",
        f"Broken: {row.broken or 'no'}",
        f"Tracks: {tracks}",
        f"Components: {components}",
        f"Confinement: {row.confinement or 'unknown'}",
        f"Grade: {row.grade or 'unknown'}",
        f"Cohort: {row.cohort_key or 'none'}",
        f"Try mode: {'yes' if row.trymode else 'no'}",
        f"Devmode: {'yes' if row.devmode else 'no'}",
    ]
    return "\n".join(lines)


def rfc3339_in(days: int) -> str:
    """Return an RFC3339 UTC timestamp ``days`` from now."""
    return (datetime.now(UTC) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class InstalledScreen(ModalScreen[None]):
    """Browse installed snaps and run the common management actions."""

    TITLE = "Installed snaps"
    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("enter", "open_store_page", "Store page"),
        ("r", "refresh", "Refresh"),
        ("u", "remove", "Remove"),
        ("h", "hold", "Hold"),
        ("v", "revert", "Revert"),
        ("d", "toggle_disabled", "Disable/Enable"),
        ("l", "logs", "Logs"),
    ]

    DEFAULT_CSS = """
    InstalledScreen {
        layout: vertical;
        background: $surface;
    }

    #installed-body {
        height: 1fr;
    }

    #installed-table-pane {
        width: auto;
    }

    #installed-table {
        width: auto;
        height: 1fr;
    }

    #installed-empty {
        width: 1fr;
        height: 1fr;
        content-align: center middle;
        color: $text-muted;
    }

    #installed-details-pane {
        width: 1fr;
    }

    #installed-details {
        width: 1fr;
        height: 1fr;
        padding: 0 1;
        border-left: solid $primary;
        overflow-y: auto;
    }

    #installed-body.narrow {
        layout: vertical;
    }

    #installed-body.narrow #installed-table-pane {
        width: 1fr;
        height: 1fr;
    }

    #installed-body.narrow #installed-table {
        width: 1fr;
    }

    #installed-body.narrow #installed-details-pane {
        width: 1fr;
        height: auto;
        max-height: 50%;
        border-top: solid $primary;
    }

    #installed-body.narrow #installed-details {
        width: 1fr;
        height: auto;
        border-left: none;
    }

    #installed-actions {
        height: auto;
        padding: 0 1;
    }

    #installed-progress {
        height: auto;
    }

    #installed-status {
        height: 1;
        padding: 0 1;
    }

    #installed-cancel {
        width: auto;
    }
    """

    def __init__(self, client: Any) -> None:
        super().__init__()
        self.client = client
        self.rows: list[InstalledSnapRow] = []
        self._rows_by_name: dict[str, InstalledSnapRow] = {}
        self.selected_name: str | None = None

        self._change_running = False
        self._change_id: str | None = None
        self._user_aborted = False
        self._pending_name: str | None = None

        self.table = DataTable(id="installed-table", cursor_type="row")
        self.empty_label = Label("No snaps installed", id="installed-empty")
        self.empty_label.display = False
        self.details = Static("", id="installed-details")
        self.details.can_focus = False

        self.refresh_button = Button("Refresh", id="installed-refresh")
        self.remove_button = Button("Remove", id="installed-remove", variant="error")
        self.cancel_button = Button("Cancel", id="installed-cancel", variant="warning")
        self.cancel_button.display = False

        self.progress = ProgressBarWithMessage(id="installed-progress")
        self.progress.display = False
        self.status_label = Label("", id="installed-status")

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        yield Horizontal(
            Vertical(
                self.table,
                self.empty_label,
                id="installed-table-pane",
            ),
            VerticalScroll(self.details, id="installed-details-pane"),
            id="installed-body",
        )
        yield Horizontal(
            self.refresh_button,
            self.remove_button,
            self.cancel_button,
            id="installed-actions",
        )
        yield self.progress
        yield self.status_label
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.table.add_columns(*TABLE_COLUMNS)
        self.table.focus()
        self._apply_layout()
        self.run_worker(
            self._load_rows(),
            group="installed-load",
            name="installed-load",
            exclusive=True,
        )

    def on_resize(self, event: events.Resize) -> None:
        self._apply_layout()

    def _table_content_width(self) -> int:
        widths = [cell_len(column) for column in TABLE_COLUMNS]
        for row in self.rows:
            cells = (
                row.name,
                row.version or "—",
                row.channel or "—",
                str(row.revision) if row.revision is not None else "—",
                row.status or "—",
            )
            widths = [
                max(width, cell_len(cell))
                for width, cell in zip(widths, cells, strict=True)
            ]
        return sum(width + 2 * self.table.cell_padding for width in widths)

    def _apply_layout(self) -> None:
        """Stack the details below the table when side-by-side would hide it."""
        if not self.is_mounted:
            return
        needed = self._table_content_width() + MIN_DETAILS_WIDTH
        self.query_one("#installed-body").set_class(self.size.width < needed, "narrow")

    # ------------------------------------------------------------------ loading
    async def _load_rows(self) -> None:
        try:
            rows = await list_installed(self.client)
        except Exception as error:
            self.rows = []
            self._rows_by_name = {}
            self.selected_name = None
            self._render_rows()
            self._show_error(error, "Error - listing installed snaps")
            return
        if not self.is_mounted:
            return
        self.rows = rows
        self._rows_by_name = {row.name: row for row in rows}
        self._render_rows()

    def _render_rows(self) -> None:
        """Rebuild the table while preserving the highlighted snap."""
        selected = self.selected_name
        self.table.clear(columns=False)
        for row in self.rows:
            self.table.add_row(
                row.name,
                row.version or "—",
                row.channel or "—",
                str(row.revision) if row.revision is not None else "—",
                row.status or "—",
                key=row.name,
            )

        has_rows = bool(self.rows)
        self.table.display = has_rows
        self.empty_label.display = not has_rows
        if not has_rows:
            self.selected_name = None
            self.details.update("")
            self._apply_layout()
            return

        names = [row.name for row in self.rows]
        index = names.index(selected) if selected in names else 0
        self.table.move_cursor(row=index, column=0)
        self.selected_name = names[index]
        self._show_details(self._rows_by_name[names[index]])
        self._apply_layout()

    def _show_details(self, row: InstalledSnapRow) -> None:
        if self.is_mounted:
            self.details.update(format_details(row))

    @on(DataTable.RowHighlighted, "#installed-table")
    def _row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        if event.data_table is not self.table:
            return
        name = event.row_key.value
        if name is None:
            return
        self.selected_name = str(name)
        row = self._rows_by_name.get(self.selected_name)
        if row is not None:
            self._show_details(row)

    @on(DataTable.RowSelected, "#installed-table")
    def _row_selected(self, event: DataTable.RowSelected) -> None:
        if event.data_table is not self.table:
            return
        self.action_open_store_page()

    # ------------------------------------------------------------------ helpers
    def _selected_row(self) -> InstalledSnapRow | None:
        if self.selected_name is not None:
            row = self._rows_by_name.get(self.selected_name)
            if row is not None:
                return row
        if self.rows and self.table.cursor_row < len(self.rows):
            self.selected_name = self.rows[self.table.cursor_row].name
            return self.rows[self.table.cursor_row]
        return None

    def _require_row(self, action: str) -> InstalledSnapRow | None:
        row = self._selected_row()
        if row is None:
            self.notify(f"Select a snap to {action}", severity="warning", timeout=3)
        return row

    def _warn(self, message: str) -> None:
        self.notify(message, severity="warning", timeout=3)

    def _set_status(self, message: str) -> None:
        if self.is_mounted:
            self.status_label.update(message)

    def _show_error(self, error: BaseException | object, title: str) -> None:
        show_error = getattr(self.app, "show_error", None)
        if callable(show_error):
            show_error(error, title)
            return
        self._set_status(f"{title}: {error}")

    def _set_busy(self, busy: bool) -> None:
        if not self.is_mounted:
            return
        self.refresh_button.disabled = busy
        self.remove_button.disabled = busy
        self.progress.display = busy
        self.cancel_button.display = busy

    # ------------------------------------------------------------------ actions
    def action_close(self) -> None:
        if self._change_running:
            self._warn(IN_PROGRESS_MESSAGE)
            return
        self.dismiss(None)

    def action_open_store_page(self) -> None:
        if self._change_running:
            self._warn(IN_PROGRESS_MESSAGE)
            return
        row = self._require_row("open")
        if row is None:
            return
        self.run_worker(
            self._open_store_page(row),
            group="installed-store-page",
            name="installed-store-page",
            exclusive=True,
        )

    async def _open_store_page(self, row: InstalledSnapRow) -> None:
        open_snap = getattr(self.app, "open_snap", None)
        if not callable(open_snap):
            self._warn("Store page is unavailable")
            return
        # The installed list stays on screen under the store page, so its
        # result-table spinner is invisible; cover this screen instead.
        self.loading = True
        try:
            # The installed row already holds the state the details page
            # renders, so opening it does not need another snapd round-trip.
            await open_snap(
                row.name,
                install_state=state_from_row(row),
                wait_for_dismiss=True,
            )
            if self.is_mounted:
                await self._load_rows()
                if self.rows:
                    self.table.focus()
        finally:
            if self.is_mounted:
                self.loading = False

    def action_refresh(self) -> None:
        row = self._require_row("refresh")
        if row is None:
            return
        name = row.name
        self._start_change(
            name,
            lambda: self.client.snaps.refresh_snap(name, channel=None, wait=False),
            f"Refreshed {name}",
            "refreshing",
            "Error - refresh snap",
        )

    def action_remove(self) -> None:
        row = self._require_row("remove")
        if row is None:
            return
        self._pending_name = row.name
        self.app.push_screen(
            ConfirmScreen(
                "Remove snap?",
                (
                    f"Remove {row.name} and all of its data? Running apps are "
                    "terminated and the snap is purged from this system."
                ),
                confirm_label="Remove",
            ),
            callback=self._remove_confirmed,
        )

    def _remove_confirmed(self, confirmed: bool | None) -> None:
        name = self._pending_name
        self._pending_name = None
        if confirmed is not True or name is None or not self.is_mounted:
            return
        self._start_change(
            name,
            lambda: self.client.snaps.remove_snap(
                name, purge=True, terminate=True, wait=False
            ),
            f"Removed {name} and its data",
            "removing",
            "Error - remove snap",
        )

    def action_hold(self) -> None:
        row = self._require_row("hold")
        if row is None:
            return
        self._pending_name = row.name
        self.app.push_screen(
            HoldScreen(row.name),
            callback=self._hold_chosen,
        )

    def _hold_chosen(self, choice: str | None) -> None:
        name = self._pending_name
        self._pending_name = None
        if choice is None or name is None or not self.is_mounted:
            return
        if choice == "unhold":
            self._start_change(
                name,
                lambda: self.client.snaps.unhold_snap(name, wait=False),
                f"Removed refresh hold on {name}",
                "removing the hold on",
                "Error - remove hold",
            )
            return
        hold_time = (
            "forever" if choice == "forever" else rfc3339_in(HOLD_DURATIONS[choice])
        )
        self._start_change(
            name,
            lambda: self.client.snaps.hold_snap(
                name,
                time=hold_time,
                hold_level="general",
                wait=False,
            ),
            f"Held refreshes for {name}",
            "holding",
            "Error - hold snap",
        )

    def action_revert(self) -> None:
        row = self._require_row("revert")
        if row is None:
            return
        self._pending_name = row.name
        self.app.push_screen(
            ConfirmScreen(
                "Revert snap?",
                (
                    f"Revert {row.name} to its previous revision? "
                    "The current revision stays installed but is no longer active."
                ),
                confirm_label="Revert",
            ),
            callback=self._revert_confirmed,
        )

    def _revert_confirmed(self, confirmed: bool | None) -> None:
        name = self._pending_name
        self._pending_name = None
        if confirmed is not True or name is None or not self.is_mounted:
            return
        self._start_change(
            name,
            lambda: self.client.snaps.revert_snap(name, wait=False),
            f"Reverted {name}",
            "reverting",
            "Error - revert snap",
        )

    def action_toggle_disabled(self) -> None:
        row = self._require_row("disable or enable")
        if row is None:
            return
        name = row.name
        if row.status == "disabled":
            operation: Callable[[], Awaitable[Any]] = partial(
                self.client.snaps.enable_snap, name, wait=False
            )
            success = f"Enabled {name}"
            busy = "enabling"
            title = "Error - enable snap"
        else:
            operation = partial(self.client.snaps.disable_snap, name, wait=False)
            success = f"Disabled {name}"
            busy = "disabling"
            title = "Error - disable snap"
        self._start_change(name, operation, success, busy, title)

    def action_logs(self) -> None:
        row = self._require_row("show logs")
        if row is None:
            return
        self.app.push_screen(LogsScreen(self.client, row.name))

    # ------------------------------------------------------------------ changes
    def _start_change(
        self,
        name: str,
        operation: Callable[[], Awaitable[Any]],
        success_message: str,
        busy_word: str,
        error_title: str,
    ) -> None:
        if self._change_running:
            self._warn(IN_PROGRESS_MESSAGE)
            return
        if self.client is None:
            self._warn("snapd is unavailable")
            return
        self._change_running = True
        self._change_id = None
        self._user_aborted = False
        self._set_busy(True)
        message = f"{busy_word.capitalize()} {name}…"
        self._set_status(message)
        self.progress.update_progress(0, None, message)
        self.run_worker(
            self._run_change(
                name,
                operation,
                success_message,
                error_title,
            ),
            group=f"installed:{name}",
            name="installed-change",
            exclusive=True,
        )

    async def _run_change(
        self,
        name: str,
        operation: Callable[[], Awaitable[Any]],
        success_message: str,
        error_title: str,
    ) -> None:
        success = False
        cancelled = False
        try:
            response = await operation()
            change_id = getattr(response, "change", None)
            if change_id is None:
                raise RuntimeError("snapd did not return a change id")
            self._change_id = str(change_id)
            await watch_change(
                self.client,
                self._change_id,
                timeout=CHANGE_TIMEOUT,
                on_change=self._on_change,
            )
            if self._user_aborted:
                self._set_status("Change cancelled")
                self.progress.update_progress(0, None, "Change cancelled")
            else:
                self.progress.update_progress(1, 1, "Operation complete")
                success = True
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as error:
            if self._user_aborted:
                self._set_status("Change cancelled")
                self.progress.update_progress(0, None, "Change cancelled")
            else:
                self.progress.update_progress(0, None, "Operation failed")
                self._show_error(error, error_title)
        finally:
            self._change_running = False
            self._change_id = None
            if self.is_mounted:
                self._set_busy(False)
                if success:
                    self._set_status(success_message)
                elif not cancelled and not self._user_aborted:
                    self._set_status("Operation failed")
                if self.client is not None:
                    with suppress(asyncio.CancelledError):
                        await self._load_rows()

    def _on_change(self, change: Any) -> None:
        done, total, message = progress_of(change)
        self.progress.update_progress(done, total, message)
        self._set_status(message)

    @on(Button.Pressed, "#installed-refresh")
    def _refresh_pressed(self) -> None:
        self.action_refresh()

    @on(Button.Pressed, "#installed-remove")
    def _remove_pressed(self) -> None:
        self.action_remove()

    @on(Button.Pressed, "#installed-cancel")
    async def _cancel_pressed(self) -> None:
        await self._abort_change()

    async def _abort_change(self) -> None:
        if not self._change_running or self._change_id is None:
            self._set_status("No operation to cancel")
            return
        change_id = self._change_id
        self._user_aborted = True
        self.progress.update_progress(0, None, "Cancelling…")
        self._set_status("Cancelling…")
        try:
            await self.client.changes.abort(change_id)
        except Exception as error:
            self._user_aborted = False
            self._show_error(error, "Error - cancel change")
