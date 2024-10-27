import traceback
from pathlib import Path

from textual import on
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Header, TextArea

MODAL_CSS_PATH = Path(__file__).parent.parent / "styles" / "error_modal.tcss"


class ErrorModal(ModalScreen):
    CSS_PATH = MODAL_CSS_PATH

    def __init__(self, exc: Exception, error_title: str | None = None):
        super().__init__()
        self.exc = exc
        self.error_text = "".join(traceback.format_exception(exc))

        self.title = error_title or "Error"
        self.text_area = TextArea(
            self.error_text, show_line_numbers=True, read_only=True
        )
        self.text_area.scroll_end(duration=0.5)

    def compose(self):
        yield Header()
        yield Vertical(
            Horizontal(self.text_area, classes="centered"),
            Horizontal(
                Button("OK", variant="error", classes="centered"),
                classes="centered button-height",
            ),
        )

    @on(Button.Pressed)
    def on_button_pressed(self):
        self.dismiss()
