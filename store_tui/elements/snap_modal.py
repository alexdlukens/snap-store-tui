import tempfile
from pathlib import Path

import httpx
import humanize
from rich_pixels import Pixels
from textual import work
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static, TextArea

from store_tui.api.snaps import SnapsAPI
from store_tui.elements.clickable_link import ClickableLink
from store_tui.elements.install_modal import InstallModal
from store_tui.elements.utils import get_platform_architecture
from store_tui.schemas.snaps.info import InfoResponse
from store_tui.schemas.snaps.search import Media

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "snap_modal.tcss"
PLACEHOLDER_ICON_URL = "https://placehold.co/64/white/black/png?text=?&font=roboto"

BASE_DIR = Path(__file__).parent.parent.parent
TEST_DIR = BASE_DIR / "tests"
TEST_DATA_DIR = TEST_DIR / "data"
PLACEHOLDER_ICON_FILEPATH = TEST_DATA_DIR / "placeholder_image.jpeg"


class SnapModal(ModalScreen):
    CSS_PATH = MODAL_CSS_PATH
    BINDINGS = {("q", "dismiss", "Close"), ("i", "modify", "Install/Modify")}

    def __init__(self, snap_name: str, api: SnapsAPI, snap_info: InfoResponse) -> None:
        super().__init__()
        self.snap_name = snap_name
        self.api = api
        self.snap_info = snap_info
        self.snap = self.snap_info.snap
        if not self.snap:
            raise ValueError(f"Snap with name {self.snap_name} not found")
        self.title = self.snap.title

        self.icon_obj = Static()
        try:
            self.download_icon()
        except Exception:
            # download fails for some reason
            # use placeholder image
            self.icon_obj = Pixels.from_image_path(
                PLACEHOLDER_ICON_FILEPATH, resize=(16, 16)
            )
            pass

        self.supported_architectures = self.get_architectures()

    @work
    async def action_modify(self):
        await self.app.push_screen(InstallModal(self.snap_info), wait_for_dismiss=True)

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
            if last_modified_date is None:
                last_modified_date = channel.created_at
                continue
            last_modified_date = max(
                last_modified_date,
                channel.created_at,
            )
        if last_modified_date is None:
            return "Unknown"
        return humanize.naturaltime(last_modified_date)

    def download_icon(self):
        """download icon for snap using icon_url and create a Pixels object"""
        if self.snap.media:
            icon_url = self.get_icon_url(self.snap.media)
        else:
            icon_url = PLACEHOLDER_ICON_URL
        self.icon_obj = None
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            icon_path = Path(f.name)
            icon_path.write_bytes(httpx.get(icon_url, timeout=5).content)
            self.icon_obj = Pixels.from_image_path(icon_path, resize=(16, 16))

    def get_icon_url(self, media: list[Media]) -> str:
        """Get the icon_url from the media list"""
        for media_obj in media:
            if media_obj.type == "icon":
                return media_obj.url
        return PLACEHOLDER_ICON_URL

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
                Label(
                    f"Supported: {'✅' if get_platform_architecture() in self.supported_architectures else '❌'} on {get_platform_architecture()}",
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
