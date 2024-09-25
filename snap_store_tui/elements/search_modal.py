from pathlib import Path

from textual.screen import ModalScreen
from textual.widgets import Input

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "search_modal.tcss"


class SnapSearchModal(ModalScreen):
    CSS_PATH = MODAL_CSS_PATH

    def __init__(self) -> None:
        super().__init__()

    def compose(self):
        yield Input(placeholder="Search Query")

    def on_input_submitted(self, text: str):
        self.dismiss(text)
