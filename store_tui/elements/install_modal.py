from pathlib import Path

from textual.screen import ModalScreen

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "snap_modal.tcss"
PLACEHOLDER_ICON_URL = "https://placehold.co/64/white/black/png?text=?&font=roboto"


class SnapModal(ModalScreen):
    CSS_PATH = MODAL_CSS_PATH
