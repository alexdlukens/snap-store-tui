import tempfile
from pathlib import Path

import httpx
import humanize
from rich_pixels import Pixels
from snap_python.client import SnapClient
from snap_python.schemas.common import BaseErrorResult, Media
from snap_python.schemas.snaps import SingleInstalledSnapResponse
from snap_python.schemas.store.info import InfoResponse
from textual import on, work
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static, TextArea

from store_tui.elements.clickable_link import ClickableLink
from store_tui.elements.install_modal import InstallModal
from store_tui.elements.utils import get_platform_architecture

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "snap_modal.tcss"

BASE_DIR = Path(__file__).parent.parent.parent
SCHEMAS_DIR = BASE_DIR / "store_tui" / "schemas"
PLACEHOLDER_ICON_FILEPATH = SCHEMAS_DIR / "images" / "placeholder.png"


class SnapModal(ModalScreen):
    CSS_PATH = MODAL_CSS_PATH
    BINDINGS = [("q", "dismiss", "Close"), ("i", "modify", "Install/Modify")]

    def __init__(
        self,
        snap_name: str,
        api: SnapClient,
        snap_info: InfoResponse,
        snap_install_data: SingleInstalledSnapResponse | None,
    ) -> None:
        super().__init__()
        self.snap_name = snap_name
        self.api = api
        self.snap_info = snap_info
        self.snap = self.snap_info.snap
        self.snap_install_data = snap_install_data

        if self.snap_install_data is None:
            self.snap_install_message = "Installed: 🚫 (snapd unaccessible)"
        elif isinstance(self.snap_install_data.result, BaseErrorResult):
            self.snap_install_message = "Installed: ❌"
        else:
            installed_version = (
                f"v{self.snap_install_data.result.version}"
                if self.snap_install_data.result.version
                else f"rev. {self.snap_install_data.result.revision}"
            )
            self.snap_install_message = f"Installed: ✅ ({installed_version})"
        if not self.snap:
            raise ValueError(f"Snap with name {self.snap_name} not found")
        self.title = self.snap.title

        self.icon_obj = Static()
        try:
            self.download_icon()
        except Exception:
            self.icon_obj = Pixels.from_image_path(
                PLACEHOLDER_ICON_FILEPATH, resize=(16, 16)
            )

        self.supported_architectures = self.get_architectures()
        self.install_button = Button(
            "Install/Modify", classes="install-button", id="install-button"
        )

    @on(Button.Pressed, "#install-button")
    async def install_button_pressed(self):
        self.action_modify()

    @work
    async def action_modify(self):
        await self.app.push_screen(
            InstallModal(
                self.snap_info, snap_install_data=self.snap_install_data, api=self.api
            ),
            wait_for_dismiss=True,
        )

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
        icon_url = self.get_icon_url(self.snap.media)
        if icon_url is None:
            raise ValueError("Icon URL not found")

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
        return None

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
                self.install_button,
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
                TextArea(self.snap.description, read_only=True, id="description-box"),
                classes="description-box",
            ),  # description
            VerticalScroll(
                Static(self.icon_obj, classes="centered snap-icon"),
                Label(
                    f"License: {self.snap.license or 'unset'}",
                    classes="details-item",
                    shrink=True,
                ),
                Label(self.snap_install_message, classes="details-item", shrink=True),
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

    def on_mount(self):
        self.set_focus(self.get_widget_by_id("description-box"))
