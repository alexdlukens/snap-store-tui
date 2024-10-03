import json
from pathlib import Path

from textual.screen import ModalScreen
from textual.widgets import Footer, Label, TextArea

from snap_store_tui.api.snaps import SnapsAPI
from snap_store_tui.schemas.snaps.search import SnapDetails

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "search_modal.tcss"


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

    def compose(self):
        yield Label(f"Selected snap: {self.snap_name}")
        yield TextArea(self.snap.model_dump_json(indent=2), read_only=True)
        yield Footer(show_command_palette=False)
