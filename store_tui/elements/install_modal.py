from pathlib import Path

import humanize
from textual.screen import ModalScreen
from textual.widgets import Footer, Tree

from store_tui.elements.utils import get_platform_architecture
from store_tui.schemas.snaps.info import ChannelMapItem, InfoResponse

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "snap_modal.tcss"
PLACEHOLDER_ICON_URL = "https://placehold.co/64/white/black/png?text=?&font=roboto"


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

    def __init__(self, snap_info: InfoResponse):
        super().__init__()
        self.snap_info = snap_info
        self.current_architecture = get_platform_architecture()
        self.build_channel_tree()

    def build_channel_tree(self):
        self.channel_tree = Tree("Channels")
        self.channel_tree.root.expand()
        self.organized_channel_tree = self.organize_channel_tree()
        architectures = list(self.organized_channel_tree.keys())

        # move current architecture to the top if it exists
        if self.current_architecture in architectures:
            architectures.remove(self.current_architecture)
            architectures.insert(0, self.current_architecture)

        for arch in architectures:
            channels = self.organized_channel_tree[arch]
            arch_node = self.channel_tree.root.add(
                arch, expand=True if self.current_architecture == arch else False
            )
            for channel in channels:
                channel_node = arch_node.add(
                    f"{channel.channel.track}/{channel.channel.risk}",
                    expand=True if channel.channel.risk == "stable" else False,
                )
                channel_node.add(f"Revision: {channel.revision}")
                channel_node.add(f"Size: {humanize.naturalsize(channel.download.size)}")
                channel_node.add(f"Version: {channel.version}")
                channel_node.add(
                    f"Released: {humanize.naturaltime(channel.channel.released_at)} ({channel.channel.released_at})"
                )
                channel_node.add(f"Confinement: {channel.confinement}")

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
        yield self.channel_tree
        yield Footer()
