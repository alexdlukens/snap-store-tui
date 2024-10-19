import datetime
import tempfile
from pathlib import Path

import humanize
import requests
from rich_pixels import Pixels
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static, TextArea

from store_tui.api.snaps import SnapsAPI
from store_tui.elements.clickable_link import ClickableLink
from store_tui.schemas.snaps.info import VALID_SNAP_INFO_FIELDS

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "snap_modal.tcss"
PLACEHOLDER_ICON_URL = "https://placehold.co/64/white/black/png?text=?&font=roboto"


class SnapModal(ModalScreen):
    CSS_PATH = MODAL_CSS_PATH
    BINDINGS = {("q", "dismiss", "Close")}

    def __init__(self, snap_name: str, api: SnapsAPI) -> None:
        super().__init__()
        self.snap_name = snap_name
        self.api = api
        self.snap_info = self.api.get_snap_info(
            snap_name=self.snap_name, fields=VALID_SNAP_INFO_FIELDS
        )
        self.snap = self.snap_info.snap
        if not self.snap:
            raise ValueError(f"Snap with name {self.snap_name} not found")
        self.title = self.snap.title

        self.icon_obj = Static()
        try:
            self.download_icon()
        except Exception:
            # download fails for some reason
            pass

        self.supported_architectures = self.get_architectures()

    def get_architectures(self) -> list[str]:
        architectures = set()
        for channel in self.snap_info.channel_map:
            if not channel.architectures:
                continue
            architectures.update(channel.architectures)
        return sorted(architectures)

    def get_last_modified_date(self) -> str:
        # get the most recent date from all channels
        last_modified_date = None
        for channel in self.snap_info.channel_map:
            if channel.created_at is not None:
                if last_modified_date is None:
                    last_modified_date = datetime.datetime.fromisoformat(
                        channel.created_at
                    )
                else:
                    last_modified_date = max(
                        last_modified_date,
                        datetime.datetime.fromisoformat(channel.created_at),
                    )
        if last_modified_date is None:
            return "Unknown"
        return humanize.naturaltime(last_modified_date)

    def download_icon(self):
        """download icon for snap using icon_url and create a Pixels object"""
        if self.snap.media:
            icon_url = self.snap.media[0].url
        else:
            icon_url = PLACEHOLDER_ICON_URL
        self.icon_obj = None
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            icon_path = Path(f.name)
            icon_path.write_bytes(requests.get(icon_url, timeout=5).content)
            self.icon_obj = Pixels.from_image_path(icon_path, resize=(16, 16))

    def compose(self):
        yield Horizontal(
            Vertical(
                Horizontal(
                    Label(self.snap.title),
                    Label(" | "),
                    Label(self.snap.publisher.display_name),
                    classes="snap-title",
                ),
                classes="title-container",
            ),
            Vertical(
                Button("Install/Modify", classes="install-button"),
                classes="button-container",
            ),
            classes="top-row",
        )
        yield Horizontal(
            Label(self.snap.summary, classes="summary"),
            classes="summary-row",
        )
        yield Horizontal(
            Vertical(
                Label("Description"),
                TextArea(self.snap.description, read_only=True),
                classes="description-box",
            ),  # description
            VerticalScroll(
                Static(self.icon_obj, classes="centered snap-icon"),
                Label(
                    f"License: {self.snap.license or 'unset'}",
                    classes="details-item",
                    shrink=True,
                ),
                ClickableLink(
                    text="Store Page",
                    url=self.snap.store_url,
                    classes="details-item link",
                    shrink=True,
                ),
                ClickableLink(
                    text="App Center Page",
                    url=f"snap://{self.snap_name}",
                    classes="details-item link",
                    shrink=True,
                ),
                Label(
                    f"Last Updated: {self.get_last_modified_date()}",
                    classes="details-item",
                    shrink=True,
                ),
                Label(
                    f"Architectures: {", ".join(self.supported_architectures)}",
                    classes="details-item",
                    shrink=True,
                ),
                classes="details-box",
            ),  # right side
            classes="main-row",
        )
        yield Footer(show_command_palette=False)
