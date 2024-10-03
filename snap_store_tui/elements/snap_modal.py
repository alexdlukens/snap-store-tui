from pathlib import Path

from textual.screen import ModalScreen
from textual.widgets import Footer, Label

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "search_modal.tcss"


class SnapModal(ModalScreen):
    CSS_PATH = MODAL_CSS_PATH
    BINDINGS = {("q", "dismiss", "Close")}

    def __init__(self, snap_id: str) -> None:
        super().__init__()
        self.snap_id = snap_id

    def compose(self):
        yield Label(f"Selected snap: {self.snap_id}")
        yield Footer(show_command_palette=False)
