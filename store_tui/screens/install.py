"""Channel picker, install settings, and install/uninstall progress."""

from __future__ import annotations

import asyncio
from contextlib import suppress

from snap_python.schemas.common import BaseErrorResult
from snap_python.schemas.store.info import ChannelMapItem, InfoResponse
from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Label,
    ListItem,
    ListView,
    SelectionList,
)
from textual.widgets.selection_list import Selection

from store_tui.client import get_platform_architecture
from store_tui.snapd import InstalledState, get_installed_state
from store_tui.widgets.channel_tree import ChannelTree, channel_label, released_sort_key
from store_tui.widgets.progress import ProgressBarWithMessage
from store_tui.widgets.settings_list import SettingsList

CHANGE_TIMEOUT = 300.0
DISMISS_BLOCKED_MESSAGE = "Operation in progress — please wait"


class InstallScreen(ModalScreen[InstalledState | None]):
    BINDINGS = [
        ("escape", "dismiss_screen", "Back"),
        ("q", "dismiss_screen", "Close"),
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

        self.channels: list[ChannelMapItem] = sorted(
            [
                item
                for item in snap_info.channel_map
                if item.channel and item.channel.architecture == self.architecture
            ],
            key=released_sort_key,
            reverse=True,
        )
        self.channel_by_label = {channel_label(item): item for item in self.channels}
        self.selected_channel: ChannelMapItem | None = (
            self.channels[0] if self.channels else None
        )

        self.is_installed = False
        self.same_channel_installed = False
        self._change_running = False
        self.settings_overrides: dict[str, bool] = {}

        self.channel_list = ListView(
            *[ListItem(Label(label), name=label) for label in self.channel_by_label],
            id="channel-list",
        )
        self.unavailable_label = Label(
            f"No channels for {self.architecture}",
            id="install-unavailable",
        )
        self.unavailable_label.display = not self.channels

        self.channel_tree = ChannelTree(self.selected_channel, id="channel-tree")
        self.settings = SettingsList(id="settings-list")
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
        self.status_label = Label("", id="install-status")
        self.status_label.display = False

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        yield Horizontal(
            Vertical(
                Label(
                    f"Channels - {self.architecture}",
                    classes="section-title",
                    id="install-channels-title",
                ),
                self.channel_list,
                self.unavailable_label,
                id="install-channels",
            ),
            Vertical(
                Horizontal(
                    self.channel_tree,
                    Vertical(
                        Label("Install settings", classes="section-title"),
                        self.settings,
                        id="install-settings",
                    ),
                    id="install-detail",
                ),
                Horizontal(
                    self.install_button,
                    self.uninstall_button,
                    id="install-actions",
                ),
                self.progress,
                self.status_label,
                id="install-main",
            ),
            id="install-body",
        )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        if self.selected_channel is not None:
            self._show_channel(self.selected_channel, preserve=False)
        self._update_installed_flags()
        self._refresh_buttons()
        if self.client is not None and self.channels:
            self.run_worker(
                self._refresh_installed(),
                group="install-state",
                name="install-state",
                exclusive=True,
            )

    # ------------------------------------------------------------------ state
    def _selected_label(self) -> str | None:
        if self.selected_channel is None:
            return None
        return channel_label(self.selected_channel)

    def _update_installed_flags(self) -> None:
        state = self.install_state
        installed = bool(state is not None and state.installed)
        self.is_installed = installed
        selected = self._selected_label()
        self.same_channel_installed = bool(
            installed
            and state is not None
            and state.channel
            and selected
            and state.channel == selected
        )

    def _refresh_buttons(self) -> None:
        has_channels = bool(self.channels)
        self.install_button.disabled = (
            not has_channels or self._change_running or self.same_channel_installed
        )
        self.uninstall_button.disabled = (
            not has_channels or self._change_running or not self.is_installed
        )

    async def _refresh_installed(self) -> None:
        with suppress(Exception):
            self.install_state = await get_installed_state(
                self.client, self.snap_info.name
            )
        self._update_installed_flags()
        self._refresh_buttons()

    # ------------------------------------------------------------------ channel UI
    @on(SelectionList.SelectionToggled)
    def _setting_toggled(self, event: SelectionList.SelectionToggled) -> None:
        value = event.selection.value
        selected = set(event.selection_list.selected)
        self.settings_overrides[value] = value in selected

    def _show_channel(self, channel: ChannelMapItem, preserve: bool = True) -> None:
        previous = self.settings.get_selection_state() if preserve else {}

        def flag(value: str, default: bool) -> bool:
            if value in self.settings_overrides:
                return self.settings_overrides[value]
            return previous.get(value, default)

        classic_state = self.settings_overrides.get(
            "classic", channel.confinement == "classic"
        )

        label = channel_label(channel)
        selections = [
            Selection("Classic", value="classic", initial_state=classic_state),
            Selection(
                "Dangerous",
                value="dangerous",
                initial_state=flag("dangerous", False),
            ),
            Selection("Devmode", value="devmode", initial_state=flag("devmode", False)),
            Selection(
                "Jailmode",
                value="jailmode",
                initial_state=flag("jailmode", False),
            ),
            Selection(
                f"Channel: {label}",
                value=label,
                initial_state=True,
                disabled=True,
            ),
        ]
        self.channel_tree.set_channel(channel)
        self.settings.update_settings(selections)

    @on(ListView.Highlighted)
    def _channel_highlighted(self, event: ListView.Highlighted) -> None:
        if event.list_view is not self.channel_list or event.item is None:
            return
        label = event.item.name
        if label is None:
            return
        channel = self.channel_by_label.get(str(label))
        if channel is None or channel is self.selected_channel:
            return
        self.selected_channel = channel
        self._show_channel(channel, preserve=True)
        self._update_installed_flags()
        self._refresh_buttons()

    # ------------------------------------------------------------------ actions
    @on(Button.Pressed, "#install-button")
    def _install_pressed(self) -> None:
        self._start_change(install=True)

    @on(Button.Pressed, "#uninstall-button")
    def _uninstall_pressed(self) -> None:
        self._start_change(install=False)

    def _start_change(self, install: bool) -> None:
        if self._change_running or self.client is None:
            return
        self._change_running = True
        self.install_button.disabled = True
        self.uninstall_button.disabled = True
        self.progress.update_progress(0, None, "Starting…")
        self.status_label.update("Operation in progress — please wait")
        if self.is_mounted:
            self.status_label.display = True
        self.run_worker(
            self._run_change(install),
            group=f"install:{self.snap_info.name}",
            name="install-change",
            exclusive=True,
        )

    async def _run_change(self, install: bool) -> None:
        action = "installing" if install else "uninstalling"
        try:
            if install:
                settings_state = self.settings.get_selection_state()
                response = await self.client.snaps.install_snap(
                    snap=self.snap_info.name,
                    channel=self._selected_label() or "stable",
                    classic=settings_state.get("classic", False),
                    dangerous=settings_state.get("dangerous", False),
                    devmode=settings_state.get("devmode", False),
                    jailmode=settings_state.get("jailmode", False),
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
        except asyncio.CancelledError:
            self.progress.update_progress(0, None, "Cancelled")
            raise
        except Exception as error:
            self.progress.update_progress(0, None, "Operation failed")
            self._show_error(error, f"Error - {action} snap")
        finally:
            self._change_running = False
            if self.is_mounted:
                self.status_label.display = False
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
            self.progress.update_progress(0, None, DISMISS_BLOCKED_MESSAGE)
            if self.is_mounted:
                self.status_label.update(DISMISS_BLOCKED_MESSAGE)
                self.status_label.display = True
                self.notify(DISMISS_BLOCKED_MESSAGE, severity="warning", timeout=3)
            return
        self.dismiss(self.install_state)
