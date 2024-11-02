from pathlib import Path

from textual.screen import ModalScreen
from textual.widgets import Footer, Tree

from store_tui.schemas.snaps.info import InfoResponse

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
        self.build_channel_tree()

    def build_channel_tree(self):
        self.channel_tree = Tree("Channels")
        self.channel_tree.root.expand()
        for channel_item in self.snap_info.channel_map:
            channel_node = self.channel_tree.root.add(channel_item.channel.name)
            channel_node.add(
                f"Arch - {', '.join(channel_item.architectures or ['None'])}"
            )
            channel_node.add(f"Revision - {channel_item.revision}")
            channel_node.add(f"Release Date - {channel_item.created_at}")

    def compose(self):
        yield self.channel_tree
        yield Footer()
