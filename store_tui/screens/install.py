"""Track/risk channel picker, install mode, and install/uninstall actions."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from rich.table import Table
from rich.text import Text
from snap_python.schemas.common import BaseErrorResult
from snap_python.schemas.store.info import ChannelMapItem, InfoResponse
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, ListItem, ListView, Static

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

CHANGE_TIMEOUT = 300.0
IN_PROGRESS_MESSAGE = "Operation in progress — please wait"


class InstallScreen(ModalScreen[InstalledState | None]):
    """Pick a track and risk, choose an install mode, then install or remove."""

    BINDINGS = [
        ("escape", "dismiss_screen", "Back"),
        ("q", "dismiss_screen", "Close"),
        ("i", "start_install", "Install"),
        ("u", "request_uninstall", "Uninstall"),
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
            id="install-actions",
        )
        yield self.progress
        yield self.status_label
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self._refresh_installed_buttons()
        self.track_list.focus()
        if self.client is not None and self.channels:
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
        if not self.channels:
            return "Install"
        if not self.is_installed:
            return f"Install {label}" if label else "Install"
        if self.same_channel_installed:
            return f"Installed from {label}"
        return f"Switch to {label}" if label else "Switch channel"

    def _refresh_buttons(self) -> None:
        self.install_button.label = self._install_button_label()
        self.install_button.disabled = (
            not self.channels or self._change_running or self.same_channel_installed
        )
        self.uninstall_button.disabled = (
            not self.channels or self._change_running or not self.is_installed
        )

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

    def action_start_install(self) -> None:
        if self._change_running:
            self._warn(IN_PROGRESS_MESSAGE)
            return
        if not self.channels:
            self._warn(f"No channels for {self.architecture}")
            return
        if self.same_channel_installed:
            self._warn(f"Already installed from {self._selected_label()}")
            return
        if self.client is None:
            self._warn("snapd is unavailable")
            return
        self._start_change(install=True)

    def action_request_uninstall(self) -> None:
        self._request_uninstall()

    def _request_uninstall(self) -> None:
        if self._change_running:
            self._warn(IN_PROGRESS_MESSAGE)
            return
        if not self.channels:
            self._warn(f"No channels for {self.architecture}")
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

    def _warn(self, message: str) -> None:
        self.notify(message, severity="warning", timeout=3)

    def _uninstall_confirmed(self, confirmed: bool | None) -> None:
        if confirmed is not True or not self.is_mounted:
            return
        self._start_change(install=False)

    def _start_change(self, install: bool) -> None:
        if self._change_running or self.client is None:
            return
        self._change_running = True
        self.install_button.disabled = True
        self.uninstall_button.disabled = True
        self.progress.display = True
        self.status_label.update(IN_PROGRESS_MESSAGE)
        self.status_label.display = True
        self.progress.update_progress(0, None, "Starting…")
        self.run_worker(
            self._run_change(install),
            group=f"install:{self.snap_info.name}",
            name="install-change",
            exclusive=True,
        )

    async def _run_change(self, install: bool) -> None:
        action = "installing" if install else "uninstalling"
        channel = self._selected_label()
        success_message: str | None = None
        cancelled = False
        try:
            if install:
                flags = mode_flags(self.mode)
                response = await self.client.snaps.install_snap(
                    snap=self.snap_info.name,
                    channel=channel or "stable",
                    classic=flags["classic"],
                    dangerous=False,
                    devmode=flags["devmode"],
                    jailmode=flags["jailmode"],
                    wait=False,
                )
            else:
                response = await self.client.snaps.remove_snap(
                    self.snap_info.name, purge=True, terminate=True, wait=False
                )
            change_id = getattr(response, "change", None)
            if change_id is None:
                raise RuntimeError("snapd did not return a change id")
            await self._wait_for_change(str(change_id))
            self.progress.update_progress(1, 1, "Operation complete")
            if install:
                success_message = f"Installed {self.snap_info.name} from {channel}"
            else:
                success_message = f"Removed {self.snap_info.name} and its data"
        except asyncio.CancelledError:
            cancelled = True
            self.progress.update_progress(0, None, "Cancelled")
            raise
        except Exception as error:
            self.progress.update_progress(0, None, "Operation failed")
            self._show_error(error, f"Error - {action} snap")
        finally:
            self._change_running = False
            if self.is_mounted:
                self.progress.display = False
                if success_message is not None:
                    self.status_label.update(success_message)
                    self.status_label.display = True
                elif not cancelled:
                    self.status_label.update("Operation failed")
                    self.status_label.display = True
            if self.is_mounted and self.client is not None:
                with suppress(asyncio.CancelledError):
                    await self._refresh_installed()

    async def _wait_for_change(self, change_id: str) -> None:
        async with asyncio.timeout(CHANGE_TIMEOUT):
            async for change in self.client.get_changes_by_id_generator(change_id):
                result = change.result
                if isinstance(result, BaseErrorResult):
                    raise RuntimeError(result.message)
                error = getattr(result, "err", None)
                if error:
                    raise RuntimeError(str(error))
                if change.ready:
                    total = max(result.overall_progress.total, 1)
                    self.progress.update_progress(total, total, "Operation complete")
                    return

                overall = result.overall_progress
                total = overall.total if overall.total and overall.total > 0 else None
                active = [task for task in result.tasks if task.status == "Doing"]
                message = active[0].summary if active else "Working…"
                self.progress.update_progress(overall.done, total, message)
        raise RuntimeError("change stream ended before completion")

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
