"""Channel detail tree."""

from __future__ import annotations

from contextlib import suppress
from datetime import UTC, datetime

import humanize
from snap_python.schemas.store.info import ChannelMapItem
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Tree

UNKNOWN = "Unknown"


def channel_label(channel: ChannelMapItem) -> str:
    """``track/risk`` label for a channel map item."""
    return f"{channel.channel.track}/{channel.channel.name}"


def released_sort_key(channel: ChannelMapItem) -> datetime:
    """None-safe sort key; unknown release dates sort last when reversed."""
    released = channel.channel.released_at
    if released is None:
        return datetime.min.replace(tzinfo=UTC)
    return released


class ChannelTree(Widget):
    """A single Tree instance, re-rendered whenever the channel changes."""

    def __init__(
        self,
        channel: ChannelMapItem | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self._channel = channel

    def compose(self):
        yield Tree(channel_label(self._channel) if self._channel else UNKNOWN)

    def on_mount(self) -> None:
        self._refresh_tree()

    def set_channel(self, channel: ChannelMapItem | None) -> None:
        self._channel = channel
        if self.is_mounted:
            self._refresh_tree()

    def _refresh_tree(self) -> None:
        with suppress(NoMatches):
            tree = self.query(Tree).first()
            if tree is not None:
                self._render_tree(tree)

    def _render_tree(self, tree: Tree) -> None:
        root = tree.root
        root.remove_children()
        if self._channel is None:
            root.label = "No channels for this architecture"
            root.expand()
            tree.refresh(layout=True)
            return

        channel = self._channel
        root.label = channel_label(channel)
        root.add_leaf(
            f"Revision: {channel.revision if channel.revision is not None else UNKNOWN}"
        )
        root.add_leaf(f"Size: {self._size_text(channel)}")
        root.add_leaf(f"Version: {channel.version or UNKNOWN}")
        released = channel.channel.released_at
        if released is None:
            root.add_leaf(f"Released: {UNKNOWN}")
        else:
            released_node = root.add(f"Released: {humanize.naturaltime(released)}")
            released_node.add(f"{released}")
        root.add_leaf(f"Confinement: {channel.confinement or UNKNOWN}")
        root.expand()
        tree.refresh(layout=True)

    @staticmethod
    def _size_text(channel: ChannelMapItem) -> str:
        download = channel.download
        if download is None or not download.size:
            return UNKNOWN
        return humanize.naturalsize(int(download.size))
