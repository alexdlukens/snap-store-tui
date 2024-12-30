from pathlib import Path

from snap_python.client import SnapClient
from snap_python.schemas.snaps import InstalledSnap, SingleInstalledSnapResponse
from snap_python.schemas.store.info import ChannelMapItem, InfoResponse
from textual import on, work
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    Footer,
    Label,
    ListItem,
    ListView,
)
from textual.widgets.selection_list import Selection
from textual.worker import Worker, WorkerState

from store_tui.elements.error_modal import ErrorModal
from store_tui.elements.progress_bar_with_message import ProgressBarWithMessage
from store_tui.elements.settings_list import SettingsList
from store_tui.elements.snap_channel_tree import SnapChannelTree
from store_tui.elements.utils import get_platform_architecture

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "install_modal.tcss"


class InstallModal(ModalScreen):
    """Installaation Page Modal

    This Modal will be used to show the available channels for the charm,
    and the history of each channel in a tree format. If installed, there should be an
    area showing the interfaces activated and interfaces that can be manually linked

    Args:
        ModalScreen (_type_): _description_
    """

    CSS_PATH = MODAL_CSS_PATH
    BINDINGS = {("q", "dismiss", "Close")}

    def __init__(
        self,
        snap_info: InfoResponse,
        snap_install_data: SingleInstalledSnapResponse | None,
        api: SnapClient,
    ) -> None:
        super().__init__()
        self.snap_info = snap_info
        self.snap_install_data = snap_install_data
        self.api = api
        self.current_architecture = get_platform_architecture()
        self.channel_info = self.organize_channel_tree()
        self.current_arch_channels = {
            f"{channel.channel.track}/{channel.channel.name}": channel
            for channel in self.channel_info.get(self.current_architecture, list())
        }
        self.sorted_channel_names = sorted(
            self.current_arch_channels.keys(),
            key=lambda x: self.current_arch_channels[x].channel.released_at,
            reverse=True,
        )
        self.available_channels = [
            ListItem(Label(channel), name=channel)
            for channel in self.sorted_channel_names
        ]
        self.channel_list = ListView(*self.available_channels)

        # get selected channel from first value in channel names
        self.selected_channel = self.available_channels[0]

        self.channel_tree = SnapChannelTree(
            self.current_arch_channels[self.selected_channel.name],
            classes="snap-channel-info",
        )
        self.is_installed = False

        if self.snap_info and isinstance(snap_install_data.result, InstalledSnap):
            self.is_installed = True

        self.snap_settings = SettingsList(id="settings-list")
        self.snap_settings_element = Vertical(
            Label("Snap Install Settings"),
            self.snap_settings,
            classes="snap-settings-box",
        )
        self.install_button = Button(
            "Install",
            classes="snap-install-buttons",
            id="install-button",
            disabled=self.is_installed,
            variant="primary",
        )
        self.uninstall_button = Button(
            "Uninstall",
            id="uninstall-button",
            classes="snap-install-buttons",
            disabled=not self.is_installed,
            variant="error",
        )
        self.install_progress_bar = ProgressBarWithMessage(classes="progress-bar")

    def toggle_is_installed(self, installed: bool = False, disable_all: bool = False):
        if disable_all:
            self.install_button.disabled = True
            self.uninstall_button.disabled = True
        else:
            self.is_installed = installed
            self.install_button.disabled = installed
            self.uninstall_button.disabled = not installed

    def update_snap_settings_list(self, channel: ChannelMapItem):
        channel_name = f"{channel.channel.track}/{channel.channel.name}"

        classic_initial_state = False
        if channel.confinement == "classic":
            classic_initial_state = True

        snap_settings_items = [
            Selection(
                "classic confinement",
                value="classic",
                initial_state=classic_initial_state,
            ),
            Selection("dangerous", value="dangerous", initial_state=False),
            Selection("devmode", value="devmode", initial_state=False),
            Selection("jailmode", value="jailmode", initial_state=False),
            Selection(
                f"channel: {channel_name}",
                value=channel_name,
                initial_state=True,
                disabled=True,
            ),
        ]
        self.snap_settings.update(snap_settings_items)

    @on(Button.Pressed, "#install-button")
    async def action_install_snap(self):
        try:
            if self.is_installed:
                raise ValueError(
                    f"{self.snap_info.name} already installed with version {self.snap_install_data.result.version}"
                )
            # get settings
            settings_state = self.snap_settings.get_selection_state()
            self.do_install_snap(
                snap=self.snap_info.name,
                channel=self.selected_channel.name,
                **settings_state,
            )

        except ValueError as e:
            self.app.push_screen(
                ErrorModal(
                    e,
                    error_title="Error",
                )
            )

    @on(Button.Pressed, "#uninstall-button")
    async def action_uninstall_snap(self):
        self.do_install_snap(install=False)

    @work(exit_on_error=False)
    async def do_install_snap(self, install: bool = True, **kwargs):
        if install:
            self.toggle_is_installed(disable_all=True)
            install_response = await self.api.snaps.install_snap(
                wait=False,
                **kwargs,
            )
            async for change in self.api.get_changes_by_id_generator(
                install_response.change
            ):
                if change.ready:
                    # set progress bar to 100% and exit loop
                    self.install_progress_bar.progress_bar.total = (
                        self.install_progress_bar.progress_bar.progress
                    )
                    self.install_progress_bar.message.update("Install Complete")
                    break
                active_tasks = [t for t in change.result.tasks if t.status == "Doing"]

                self.install_progress_bar.progress_bar.total = (
                    change.result.overall_progress.total
                )
                self.install_progress_bar.progress_bar.progress = (
                    change.result.overall_progress.done
                )
                if active_tasks:
                    self.install_progress_bar.message.update(active_tasks[0].summary)
            self.toggle_is_installed(installed=True)

        else:
            self.toggle_is_installed(disable_all=True)
            uninstall_response = await self.api.snaps.remove_snap(
                self.snap_info.name, purge=True, terminate=True, wait=False
            )
            async for change in self.api.get_changes_by_id_generator(
                uninstall_response.change
            ):
                if change.ready:
                    # set progress bar to 100% and exit loop
                    self.install_progress_bar.progress_bar.total = (
                        self.install_progress_bar.progress_bar.progress
                    )
                    self.install_progress_bar.message.update("Uninstall Complete")
                    break

                active_tasks = [t for t in change.result.tasks if t.status == "Doing"]
                self.install_progress_bar.progress_bar.total = (
                    change.result.overall_progress.total
                )
                self.install_progress_bar.progress_bar.progress = (
                    change.result.overall_progress.done
                )
                if active_tasks:
                    self.install_progress_bar.message.update(active_tasks[0].summary)
            self.toggle_is_installed(installed=False)

    @on(Worker.StateChanged)
    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Called when the worker state changes."""
        if event.state == WorkerState.ERROR:
            self.toggle_is_installed(installed=self.is_installed)
            self.app.push_screen(
                ErrorModal(
                    event.worker.error,
                    error_title="Error in install worker",
                )
            )
        elif event.state == WorkerState.SUCCESS:
            pass
        else:
            pass

    @on(ListView.Selected)
    @on(ListView.Highlighted)
    def channel_list_selected(self, selected_item: ListView.Selected):
        self.selected_channel = selected_item.item
        self.channel_tree.update_tree(
            self.current_arch_channels[self.selected_channel.name]
        )
        self.update_snap_settings_list(
            self.current_arch_channels[self.selected_channel.name]
        )

    def organize_channel_tree(self) -> dict[str, list[ChannelMapItem]]:
        """Organize channels by architecture, then track"""

        architectures = set()
        for channel_item in self.snap_info.channel_map:
            architectures.add(channel_item.channel.architecture)

        organized_channels = {}
        for architecture in architectures:
            channels = [
                c
                for c in self.snap_info.channel_map
                if c.channel.architecture == architecture
            ]
            organized_channels[architecture] = sorted(
                channels, key=lambda x: x.channel.released_at, reverse=True
            )

        return organized_channels

    def compose(self):
        yield Horizontal(
            Container(
                Label(f"Channels - {self.current_architecture}", expand=True),
                self.channel_list,
                classes="channel-list",
            ),
            Vertical(
                Horizontal(
                    self.channel_tree,
                    Vertical(
                        self.snap_settings_element,
                        Horizontal(
                            self.install_button,
                            self.uninstall_button,
                            classes="install-buttons-box",
                        ),
                        classes="snap-settings",
                    ),
                    classes="all-snap-details",
                ),
                self.install_progress_bar,
                classes="main-content",
            ),
        )
        yield Footer()
