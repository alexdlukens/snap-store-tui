from pathlib import Path

from snap_python.client import SnapClient
from snap_python.schemas.snaps import InstalledSnap, SingleInstalledSnapResponse
from snap_python.schemas.store.info import ChannelMapItem, InfoResponse
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Footer, Placeholder

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

        if not self.snap_info:
            self.is_installed = False
        elif isinstance(snap_install_data.result, InstalledSnap):
            self.is_installed = True
        else:
            self.is_installed = False

    def action_install_snap(self):
        pass

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
            Placeholder("channel-list", classes="channel-list"),
            Container(
                Horizontal(
                    Placeholder("snap-details", classes="snap-channel-info"),
                    Container(
                        Placeholder("snap-settings", classes="snap-settings-box"),
                        Placeholder(
                            "snap-install-buttons", classes="snap-install-buttons"
                        ),
                        classes="snap-settings",
                    ),
                    classes="all-snap-details",
                ),
                Placeholder("progress-bar", classes="progress-bar"),
                classes="main-content",
            ),
        )
        yield Footer()
