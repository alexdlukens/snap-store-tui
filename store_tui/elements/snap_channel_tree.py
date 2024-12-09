import humanize
from snap_python.schemas.store.info import ChannelMapItem
from textual.widget import Widget
from textual.widgets import Tree


class SnapChannelTree(Widget):
    def __init__(
        self, channel: ChannelMapItem, name=None, id=None, classes=None, disabled=False
    ):
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self.channel = channel
        self.update_tree(channel)

    def update_tree(self, channel: ChannelMapItem):
        self.channel = channel
        channel_name = f"{channel.channel.track}/{channel.channel.name}"
        self.channel_tree = Tree(channel_name, classes="snap-channel-info")
        self.channel_tree.styles.overflow_x = "hidden"
        self.channel_tree.root.expand()
        self.channel_tree.root.add_leaf(f"Revision: {channel.revision}")
        self.channel_tree.root.add_leaf(
            f"Size: {humanize.naturalsize(channel.download.size)}"
        )
        self.channel_tree.root.add_leaf(f"Version: {channel.version}")
        release_node = self.channel_tree.root.add(
            f"Released: {humanize.naturaltime(channel.channel.released_at)}"
        )
        release_node.add(f"{channel.channel.released_at}")
        self.channel_tree.root.add_leaf(f"Confinement: {channel.confinement}")

        if self.is_mounted:
            self.refresh(recompose=True)

    def compose(self):
        yield self.channel_tree
