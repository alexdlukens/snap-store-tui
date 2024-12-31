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


class InstallModal(ModalScreen[SingleInstalledSnapResponse]):
    """Installaation Page Modal

    This Modal will be used to show the available channels for the charm,
    and the history of each channel in a tree format. If installed, there should be an
    area showing the interfaces activated and interfaces that can be manually linked

    Args:
        ModalScreen (_type_): _description_
    """

    CSS_PATH = MODAL_CSS_PATH
    BINDINGS = {("q", "dismiss_with_install_info", "Close")}

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
            variant="primary",
        )
        self.uninstall_button = Button(
            "Uninstall",
            id="uninstall-button",
            classes="snap-install-buttons",
            variant="error",
        )
        self.install_progress_bar = ProgressBarWithMessage(classes="progress-bar")
        self.is_installed = False
        self.same_channel_installed = False

    async def action_dismiss_with_install_info(self):
        return self.dismiss(self.snap_install_data)

    async def on_mount(self):
        await self.toggle_is_installed()

    async def check_is_installed(self):
        """
        Asynchronously checks if the snap is installed and updates the installation status.
        This method retrieves the installation information of the snap using the API and
        updates the `is_installed` and `same_channel_installed` attributes based on the
        retrieved data.
        Attributes:
            snap_install_data (SnapInfo): The installation data of the snap.
            is_installed (bool): True if the snap is installed, False otherwise.
            same_channel_installed (bool): True if the installed snap is on the same channel
                                           as the selected channel, False otherwise.
        """

        # no api access
        if not self.snap_install_data:
            self.is_installed = False
            self.same_channel_installed = False
            return

        # get installed snap info
        self.snap_install_data = await self.api.snaps.get_snap_info(self.snap_info.name)
        if self.snap_install_data and isinstance(
            self.snap_install_data.result, InstalledSnap
        ):
            self.is_installed = True
            self.same_channel_installed = (
                self.snap_install_data.result.channel == self.selected_channel.name
            )
        else:
            self.is_installed = False
            self.same_channel_installed = False

    async def toggle_is_installed(self, disable_all: bool = False):
        """
        Asynchronously toggles the installation status of the application.
        This method enables or disables the install and uninstall buttons based on
        the installation status of the application. If `disable_all` is set to True,
        both buttons will be disabled regardless of the installation status.
        Args:
            disable_all (bool): If True, disables both install and uninstall buttons.
                                Defaults to False.
        """

        if disable_all:
            self.install_button.disabled = True
            self.uninstall_button.disabled = True
        else:
            await self.check_is_installed()
            # TODO: this needs to be implemented in snap-python: "and self.same_channel_installed"
            self.install_button.disabled = self.is_installed
            self.uninstall_button.disabled = not self.is_installed

    def update_snap_settings_list(self, channel: ChannelMapItem):
        """Update channel details, available snap settings when switching branches

        Args:
            channel (ChannelMapItem): the new channel
        """
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
        """
        Asynchronously installs a snap package using the selected settings and channel.
        This method retrieves the current selection state from snap settings and attempts to install
        the snap package specified by `self.snap_info.name` on the selected channel. If an error occurs
        during the installation process, an error modal is displayed with the error message.
        Raises:
            ValueError: If there is an issue with the installation process.
        """

        try:
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
        """
        Perform the installation or removal of a snap package asynchronously.
        This method handles the installation or removal of a snap package based on the
        `install` parameter. It updates the installation progress bar and status messages
        accordingly.
        Args:
            install (bool): If True, install the snap package. If False, remove the snap package.
            **kwargs: Additional keyword arguments to pass to the snap installation or removal API.
        Returns:
            None
        Raises:
            Exception: If there is an error during the snap installation or removal process.
        """

        await self.toggle_is_installed(disable_all=True)
        if install:
            response = await self.api.snaps.install_snap(
                wait=False,
                **kwargs,
            )
        else:
            response = await self.api.snaps.remove_snap(
                self.snap_info.name, purge=True, terminate=True, wait=False
            )

        async for change in self.api.get_changes_by_id_generator(response.change):
            if change.ready:
                # set progress bar to 100% and exit loop
                self.install_progress_bar.progress_bar.total = (
                    self.install_progress_bar.progress_bar.progress
                )
                self.install_progress_bar.message.update("Operation Complete")
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

    @on(Worker.StateChanged)
    async def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """
        Called when the installation worker's state changes.

        This method handles the state changes of a worker. If the worker state is
        `ERROR`, it toggles the installation status and displays an error modal
        with the error message. If the worker state is `SUCCESS`, it fetches and
        updates the snap installation data.

        Args:
            event (Worker.StateChanged): The event object containing the new state
            of the worker.
        """

        if event.state == WorkerState.ERROR:
            await self.toggle_is_installed()
            self.app.push_screen(
                ErrorModal(
                    event.worker.error,
                    error_title="Error in install worker",
                )
            )
        elif event.state == WorkerState.SUCCESS:
            await self.toggle_is_installed()

    @on(ListView.Selected)
    @on(ListView.Highlighted)
    async def channel_list_selected(self, selected_item: ListView.Selected):
        """
        Handles the event when a channel is selected from the list.

        Args:
            selected_item (ListView.Selected): The selected item from the list view.

        Updates:
            self.selected_channel: Sets the selected channel to the item from the selected list view.
            self.channel_tree: Updates the channel tree with the channels of the current architecture.
            self.update_snap_settings_list: Updates the snap settings list with the channels of the current architecture.
        """
        self.selected_channel = selected_item.item
        self.channel_tree.update_tree(
            self.current_arch_channels[self.selected_channel.name]
        )
        self.update_snap_settings_list(
            self.current_arch_channels[self.selected_channel.name]
        )
        await self.toggle_is_installed()

    def organize_channel_tree(self) -> dict[str, list[ChannelMapItem]]:
        """
        Organize channels by architecture and sort them by release date.

        This method processes the `channel_map` attribute of `snap_info` to group
        channels by their architecture. Each group of channels is then sorted in
        descending order based on their release date.

        Returns:
            dict[str, list[ChannelMapItem]]: A dictionary where the keys are
            architecture strings and the values are lists of `ChannelMapItem`
            objects sorted by their release date in descending order.
        """

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
