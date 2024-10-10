import json
import tempfile
from pathlib import Path

import requests
from rich_pixels import Pixels
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label, Static, TextArea

from snap_store_tui.api.snaps import SnapsAPI
from snap_store_tui.schemas.snaps.search import SnapDetails

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "snap_modal.tcss"


class SnapModal(ModalScreen):
    CSS_PATH = MODAL_CSS_PATH
    BINDINGS = {("q", "dismiss", "Close")}

    def __init__(self, snap_name: str, api: SnapsAPI) -> None:
        super().__init__()
        self.snap_name = snap_name
        self.api = api
        self.snap = self.api.get_snap_details(snap_name=self.snap_name)
        self.snap = SnapDetails.model_validate(self.snap)
        if not self.snap:
            raise ValueError(f"Snap with name {self.snap_name} not found")
        self.title = self.snap.title

        self.icon_obj = Static()
        try:
            self.download_icon()
        except Exception:
            # download fails for some reason
            pass

    def download_icon(self):
        # download image using icon_url
        icon_url = self.snap.icon_url
        if not icon_url:
            icon_url = "https://placehold.co/64/white/black/png?text=?&font=roboto"
        self.icon_obj = None
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            icon_path = Path(f.name)
            icon_path.write_bytes(requests.get(icon_url).content)
            self.icon_obj = Pixels.from_image_path(icon_path, resize=(16, 16))

    def compose(self):
        yield Horizontal(
            Vertical(
                Horizontal(
                    Label(self.snap.title),
                    Label(" | "),
                    Label(self.snap.publisher),
                    classes="snap-title",
                ),
                classes="title-container",
            ),
            Vertical(
                Button("Install", classes="install-button"), classes="button-container"
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
            Vertical(
                Static(self.icon_obj, classes="centered"),
                TextArea(
                    f"License: {self.snap.license}", disabled=True, soft_wrap=True
                ),
                classes="details-box",
            ),  # right side
            classes="main-row",
        )
        yield Footer(show_command_palette=False)
