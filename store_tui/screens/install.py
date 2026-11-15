"""Track/risk channel picker, install mode, and install/uninstall actions."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from rich.table import Table
from rich.text import Text
from snap_python.schemas.store.info import ChannelMapItem, InfoResponse
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, ListItem, ListView, Static

from store_tui.changes import progress_of, watch_change
from store_tui.channels import (
    MODE_HINTS,
    MODES,
    channel_label,
    channels_for_architecture,
    default_mode,
    default_risk,
    default_track,
    find_channel,
    mode_entry_label,
    mode_flags,
    order_tracks,
    release_rows,
    risk_entry_label,
    risks_for_track,
)
from store_tui.client import get_platform_architecture
from store_tui.screens.confirm import ConfirmScreen
from store_tui.snapd import InstalledState, get_installed_state
from store_tui.widgets.progress import ProgressBarWithMessage

IN_PROGRESS_MESSAGE = "Operation in progress — please wait"
ACTION_TITLES = {
    "install": "installing snap",
    "refresh": "updating snap",
    "switch": "switching channel",
    "revert": "reverting snap",
    "remove": "uninstalling snap",
}


class InstallScreen(ModalScreen[InstalledState | None]):
    """Pick a track and risk, choose an install mode, then install or remove."""

    BINDINGS = [
        ("escape", "dismiss_screen", "Back"),
        ("q", "dismiss_screen", "Close"),
        ("i", "start_install", "Install"),
        ("u", "request_uninstall", "Uninstall"),
        ("r", "revert", "Revert"),
    ]

    def __init__(
        self,
        snap_info: InfoResponse,
        install_state: InstalledState | None,
        client,
    ) -> None:
        super().__init__()
        self.snap_info = snap_info
        self.install_state = install_state
        self.client = client
        self.architecture = get_platform_architecture()

        self.channels = channels_for_architecture(
            snap_info.channel_map, self.architecture
        )
        self.tracks = order_tracks(self.channels)
        longest_track = max((len(track) for track in self.tracks), default=0)
        self.track_width = max(12, min(26, longest_track + 3))

        self.is_installed = False
        self.installed_channel: str | None = (
            install_state.channel
            if install_state is not None and install_state.installed
            else None
        )
        self.same_channel_installed = False
        self._change_running = False
        self._change_id: str | None = None
        self._cancel_requested = False
        self._mode_explicit = False

        # Initial selection defaults, then populate the panes.
        self.selected_track = default_track(
            self.channels,
            self.installed_channel,
            snap_info.default_track,
        )
        self.selected_risk = default_risk(
            self.channels, self.selected_track, self.installed_channel
        )
        self.selected_channel = find_channel(
            self.channels, self.selected_track, self.selected_risk
        )
        self.mode = default_mode(self.selected_channel)
        self.risk_items: list[ChannelMapItem] = self._items_for_selected_track()

        self.track_list = ListView(
            *[ListItem(Label(track), name=track) for track in self.tracks],
            initial_index=self._index(self.tracks, self.selected_track),
            id="track-list",
        )
        self.track_list.styles.width = self.track_width
        risk_names = [item.channel.name for item in self.risk_items]
        self.risk_list = ListView(
            *[
                ListItem(
                    Label(risk_entry_label(item, self.installed_channel)),
                    name=item.channel.name,
                )
                for item in self.risk_items
            ],
            initial_index=self._index(risk_names, self.selected_risk),
            id="risk-list",
        )

        self.release_title = Label("Release", classes="section-title")
        self.release_details = Static(self._details_renderable(), id="release-details")
        self.mode_title = Label("Install mode", classes="section-title")
        self.mode_list = ListView(
            *[
                ListItem(
                    Label(mode_entry_label(mode, mode == self.mode)),
                    name=mode,
                )
                for mode in MODES
            ],
            initial_index=MODES.index(self.mode),
            id="mode-list",
        )
        self.mode_hint = Label(MODE_HINTS[self.mode], id="mode-hint")
        self.unavailable_label = Label(
            f"No channels for {self.architecture}",
            id="install-unavailable",
        )
        self._sync_availability()

        self.side = VerticalScroll(
            self.release_title,
            self.release_details,
            self.mode_title,
            self.mode_list,
            self.mode_hint,
            self.unavailable_label,
            id="install-side",
        )
        self.side.can_focus = False

        self.install_button = Button(
            "Install",
            id="install-button",
            variant="primary",
            disabled=not self.channels,
        )
        self.uninstall_button = Button(
            "Uninstall",
            id="uninstall-button",
            variant="error",
            disabled=True,
        )
        self.revert_button = Button(
            "Revert",
            id="revert-button",
            disabled=True,
        )
        self.cancel_button = Button(
            "Cancel",
            id="cancel-button",
            variant="warning",
        )
        self.cancel_button.display = False
        self.progress = ProgressBarWithMessage(id="install-progress")
        self.progress.display = False
        self.status_label = Label("", id="install-status")
        self.status_label.display = False

        self.title_label = Label("", id="install-title")
        self.badge_label = Label("", id="install-badge")
        self.subtitle_label = Label("", id="install-subtitle")

        self._update_installed_flags()
        self._update_header()
        self._refresh_buttons()

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        yield Vertical(
            Horizontal(
                self.title_label,
                self.badge_label,
                id="install-title-row",
            ),
            self.subtitle_label,
            id="install-header",
        )
        yield Horizontal(
            Vertical(
                Label("Track", classes="section-title"),
                self.track_list,
                id="install-tracks",
            ),
            Vertical(
                Label("Risk", classes="section-title"),
                self.risk_list,
                id="install-risks",
            ),
            self.side,
            id="install-body",
        )
        yield Horizontal(
            self.install_button,
            self.uninstall_button,
            self.revert_button,
            self.cancel_button,
            id="install-actions",
        )
        yield self.progress
        yield self.status_label
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self._refresh_installed_buttons()
        self.track_list.focus()
        if self.client is not None:
            self.run_worker(
                self._refresh_installed(),
                group="install-state",
                name="install-state",
                exclusive=True,
            )

    # ------------------------------------------------------------------ panes
    @staticmethod
    def _index(values: list[str], value: str | None) -> int | None:
        if value is None or value not in values:
            return None
        return values.index(value)

    def _items_for_selected_track(self) -> list[ChannelMapItem]:
        if self.selected_track is None:
            return []
        return risks_for_track(self.channels, self.selected_track)

    async def _rebuild_risk_list(self) -> None:
        """Re-render the Risk pane after a track or installed-state change."""
        self.risk_items = self._items_for_selected_track()
        self.risk_list.index = None
        await self.risk_list.clear()
        await self.risk_list.extend(
            [
                ListItem(
                    Label(risk_entry_label(item, self.installed_channel)),
                    name=item.channel.name,
                )
                for item in self.risk_items
            ]
        )
        names = [item.channel.name for item in self.risk_items]
        if self.selected_risk in names:
            self.risk_list.index = names.index(self.selected_risk)

    @on(ListView.Highlighted, "#track-list")
    async def _track_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if item is None or item.name is None:
            return
        track = str(item.name)
        if track == self.selected_track:
            return
        self.selected_track = track
        self.selected_risk = default_risk(self.channels, track, self.installed_channel)
        self.selected_channel = find_channel(
            self.channels, self.selected_track, self.selected_risk
        )
        await self._rebuild_risk_list()
        self._channel_changed()

    @on(ListView.Highlighted, "#risk-list")
    def _risk_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if item is None or item.name is None:
            return
        risk = str(item.name)
        if risk == self.selected_risk:
            return
        self.selected_risk = risk
        self.selected_channel = find_channel(
            self.channels, self.selected_track, self.selected_risk
        )
        self._channel_changed()

    def _channel_changed(self) -> None:
        self._update_installed_flags()
        self.release_details.update(self._details_renderable())
        if not self._mode_explicit:
            self._set_mode(default_mode(self.selected_channel))
        self._refresh_buttons()

    # ------------------------------------------------------------------ mode
    def _update_mode_markers(self) -> None:
        """Repaint the ●/○ markers in place, without rebuilding the list."""
        for item in self.mode_list.children:
            if item.name is None:
                continue
            label = item.query(Label).first()
            if label is not None:
                label.update(
                    mode_entry_label(str(item.name), str(item.name) == self.mode)
                )

    def _set_mode(self, mode: str) -> None:
        """Set the mode without treating it as an explicit user choice."""
        self.mode = mode
        index = MODES.index(mode)
        if self.mode_list.index != index:
            self.mode_list.index = index
        self._update_mode_markers()
        self.mode_hint.update(MODE_HINTS[mode])

    @on(ListView.Highlighted, "#mode-list")
    def _mode_highlighted(self, event: ListView.Highlighted) -> None:
        item = event.item
        if item is None or item.name is None:
            return
        mode = str(item.name)
        if mode == self.mode:
            return
        self.mode = mode
        self._mode_explicit = True
        self._update_mode_markers()
        self.mode_hint.update(MODE_HINTS[mode])

    # ------------------------------------------------------------------ header
    def _snap_name(self) -> str:
        return (
            self.snap_info.snap.title
            or self.snap_info.snap.name
            or self.snap_info.name
            or "snap"
        )

    def _installed_text(self) -> str:
        state = self.install_state
        if state is None or not state.installed:
            if state is not None and state.error:
                return "Installed state unavailable"
            return "Not installed"
        version = state.version or (
            f"rev {state.revision}" if state.revision is not None else "unknown"
        )
        return f"Installed {version} on {state.channel or 'unknown channel'}"

    def _subtitle_text(self) -> str:
        publisher = (
            self.snap_info.snap.publisher.display_name
            if self.snap_info.snap.publisher is not None
            else "Unknown publisher"
        )
        return f"{self.architecture} · {publisher}"

    def _update_header(self) -> None:
        action = "Manage" if self.is_installed else "Install"
        self.title_label.update(f"{action} {self._snap_name()}")
        self.badge_label.update(self._installed_text())
        self.subtitle_label.update(self._subtitle_text())

    def _sync_availability(self) -> None:
        """Show either the channel UI or the single unavailable message."""
        has_channels = bool(self.channels)
        self.release_title.display = has_channels
        self.release_details.display = has_channels
        self.mode_title.display = has_channels
        self.mode_list.display = has_channels
        self.mode_hint.display = has_channels
        self.unavailable_label.display = not has_channels

    def _details_renderable(self) -> Table | Text:
        if self.selected_channel is None:
            return Text(
                f"No channels for {self.architecture}",
                style="dim",
            )
        table = Table.grid(padding=(0, 1))
        table.add_column(style="dim", no_wrap=True)
        table.add_column()
        for key, value in release_rows(self.selected_channel):
            table.add_row(key, value)
        return table

    # ------------------------------------------------------------------ state
    def _selected_label(self) -> str | None:
        if self.selected_channel is None:
            return None
        return channel_label(self.selected_channel)

    def _update_installed_flags(self) -> None:
        state = self.install_state
        installed = bool(state is not None and state.installed)
        self.is_installed = installed
        self.installed_channel = state.channel if installed else None
        selected = self._selected_label()
        self.same_channel_installed = bool(
            installed
            and state is not None
            and state.channel
            and selected
            and state.channel == selected
        )

    def _install_button_label(self) -> str:
        label = self._selected_label()
        if not self.channels or label is None:
            return "Install"
        if not self.is_installed:
            return f"Install {label}"
        if self.same_channel_installed:
            return f"Update from {label}"
        return f"Switch to {label}"

    def _refresh_buttons(self) -> None:
        self.install_button.label = self._install_button_label()
        self.install_button.disabled = (
            self._change_running or not self.channels or self._selected_label() is None
        )
        self.uninstall_button.disabled = self._change_running or not self.is_installed
        self.revert_button.disabled = self._change_running or not self.is_installed
        self.cancel_button.display = self._change_running
        self.cancel_button.disabled = self._cancel_requested

    def _refresh_installed_buttons(self) -> None:
        self._update_installed_flags()
        self._update_header()
        self._refresh_buttons()

    async def _refresh_installed(self) -> None:
        with suppress(Exception):
            self.install_state = await get_installed_state(
                self.client, self.snap_info.name
            )
        self._refresh_installed_buttons()
        if self.is_mounted:
            await self._rebuild_risk_list()

    # ------------------------------------------------------------------ actions
    @on(Button.Pressed, "#install-button")
    def _install_pressed(self) -> None:
        self.action_start_install()

    @on(Button.Pressed, "#uninstall-button")
    def _uninstall_pressed(self) -> None:
        self._request_uninstall()

    @on(Button.Pressed, "#revert-button")
    def _revert_pressed(self) -> None:
        self._request_revert()

    @on(Button.Pressed, "#cancel-button")
    async def _cancel_pressed(self) -> None:
        await self._request_cancel()

    def action_start_install(self) -> None:
        if self._change_running:
            self._warn(IN_PROGRESS_MESSAGE)
            return
        if not self.channels:
            self._warn(f"No channels for {self.architecture}")
            return
        if self.client is None:
            self._warn("snapd is unavailable")
            return
        if not self.is_installed:
            self._start_change("install")
        elif self.same_channel_installed:
            self._start_change("refresh")
        else:
            self._start_change("switch")

    def action_request_uninstall(self) -> None:
        self._request_uninstall()

    def action_revert(self) -> None:
        self._request_revert()

    def _request_uninstall(self) -> None:
        if self._change_running:
            self._warn(IN_PROGRESS_MESSAGE)
            return
        if not self.is_installed:
            self._warn(f"Nothing to uninstall — {self._snap_name()} is not installed")
            return
        if self.client is None:
            self._warn("snapd is unavailable")
            return
        self.app.push_screen(
            ConfirmScreen(
                "Uninstall snap?",
                (
                    f"Remove {self._snap_name()} and all of its data? "
                    "Running apps are terminated and the snap is purged "
                    "from this system."
                ),
                confirm_label="Uninstall",
            ),
            callback=self._uninstall_confirmed,
        )

    def _request_revert(self) -> None:
        if self._change_running:
            self._warn(IN_PROGRESS_MESSAGE)
            return
        if not self.is_installed:
            self._warn(f"Nothing to revert — {self._snap_name()} is not installed")
            return
        if self.client is None:
            self._warn("snapd is unavailable")
            return
        self.app.push_screen(
            ConfirmScreen(
                "Revert snap?",
                f"Revert {self._snap_name()} to its previous revision?",
                confirm_label="Revert",
            ),
            callback=self._revert_confirmed,
        )

    def _warn(self, message: str) -> None:
        self.notify(message, severity="warning", timeout=3)

    def _uninstall_confirmed(self, confirmed: bool | None) -> None:
        if confirmed is not True or not self.is_mounted:
            return
        self._start_change("remove")

    def _revert_confirmed(self, confirmed: bool | None) -> None:
        if confirmed is not True or not self.is_mounted:
            return
        self._start_change("revert")

    async def _request_cancel(self) -> None:
        if not self._change_running or self._cancel_requested:
            return
        self._cancel_requested = True
        self._refresh_buttons()
        self.status_label.update("Cancelling…")
        self.status_label.display = True
        change_id = self._change_id
        if change_id is None:
            return
        try:
            await self.client.changes.abort(change_id)
        except Exception as error:
            # An abort race must not replace a working screen with an error.
            self._cancel_requested = False
            self._refresh_buttons()
            self._warn(f"Could not cancel operation: {error}")

    def _start_change(self, action: str) -> None:
        if self._change_running or self.client is None:
            return
        self._change_running = True
        self._change_id = None
        self._cancel_requested = False
        self._refresh_buttons()
        self.progress.display = True
        self.status_label.update(IN_PROGRESS_MESSAGE)
        self.status_label.display = True
        self.progress.update_progress(0, None, "Starting…")
        self.run_worker(
            self._run_change(action),
            group=f"install:{self.snap_info.name}",
            name="install-change",
            exclusive=True,
        )

    async def _run_change(self, action: str) -> None:
        name = self.snap_info.name
        channel = self._selected_label()
        success_message: str | None = None
        cancelled = False
        failed = False
        try:
            response = await self._request_change(action)
            change_id = getattr(response, "change", None)
            if change_id is None:
                raise RuntimeError("snapd did not return a change id")
            self._change_id = str(change_id)
            if self._cancel_requested:
                with suppress(Exception):
                    await self.client.changes.abort(self._change_id)
            await watch_change(
                self.client,
                self._change_id,
                on_change=self._progress_change,
            )
            self.progress.update_progress(1, 1, "Operation complete")
            if self._cancel_requested:
                cancelled = True
            elif action == "install":
                success_message = f"Installed {name} from {channel}"
            elif action == "refresh":
                success_message = f"Updated {name} from {channel}"
            elif action == "switch":
                success_message = f"Switched {name} to {channel}"
            elif action == "revert":
                success_message = f"Reverted {name}"
            else:
                success_message = f"Removed {name} and its data"
        except asyncio.CancelledError:
            cancelled = True
            self.progress.update_progress(0, None, "Cancelled")
            raise
        except Exception as error:
            if self._cancel_requested:
                cancelled = True
            else:
                failed = True
                self.progress.update_progress(0, None, "Operation failed")
                self._show_error(error, f"Error - {ACTION_TITLES[action]}")
        finally:
            self._change_running = False
            self._change_id = None
            if self.is_mounted:
                self.progress.display = False
                if success_message is not None:
                    self.status_label.update(success_message)
                    self.status_label.display = True
                elif cancelled:
                    self.progress.update_progress(0, None, "Operation cancelled")
                    self.status_label.update("Operation cancelled")
                    self.status_label.display = True
                elif failed:
                    self.status_label.update("Operation failed")
                    self.status_label.display = True
                self._refresh_buttons()
            if self.is_mounted and self.client is not None:
                with suppress(asyncio.CancelledError):
                    await self._refresh_installed()

    async def _request_change(self, action: str):
        name = self.snap_info.name
        if action == "install":
            flags = mode_flags(self.mode)
            return await self.client.snaps.install_snap(
                snap=name,
                channel=self._selected_label(),
                classic=flags["classic"],
                dangerous=False,
                devmode=flags["devmode"],
                jailmode=flags["jailmode"],
                wait=False,
            )
        if action == "refresh":
            return await self.client.snaps.refresh_snap(name, channel=None, wait=False)
        if action == "switch":
            return await self.client.snaps.switch_channel(
                name, channel=self._selected_label(), wait=False
            )
        if action == "revert":
            return await self.client.snaps.revert_snap(name, wait=False)
        return await self.client.snaps.remove_snap(
            name, purge=True, terminate=True, wait=False
        )

    def _progress_change(self, change) -> None:
        if not self.is_mounted:
            return
        done, total, message = progress_of(change)
        if change.ready:
            complete = total or done or 1
            self.progress.update_progress(complete, complete, "Operation complete")
            return
        self.progress.update_progress(done, total, message)

    def _show_error(self, error: BaseException, title: str) -> None:
        show_error = getattr(self.app, "show_error", None)
        if callable(show_error):
            show_error(error, title)

    def action_dismiss_screen(self) -> None:
        if self._change_running:
            self.progress.update_progress(0, None, IN_PROGRESS_MESSAGE)
            if self.is_mounted:
                self.status_label.update(IN_PROGRESS_MESSAGE)
                self.status_label.display = True
                self.notify(IN_PROGRESS_MESSAGE, severity="warning", timeout=3)
            return
        self.dismiss(self.install_state)
