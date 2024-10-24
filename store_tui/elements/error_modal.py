import traceback

from textual import on
from textual.screen import ModalScreen
from textual.widgets import Button, Header, TextArea


class ErrorModal(ModalScreen):
    def __init__(self, exc: Exception, error_title: str | None = None):
        super().__init__()
        self.exc = exc
        self.error_text = "".join(traceback.format_exception(exc))

        self.title = error_title or "Error"

    def compose(self):
        yield Header()
        yield TextArea(self.error_text, show_line_numbers=True)
        yield Button("OK", variant="error")

    @on(Button.Pressed)
    def on_button_pressed(self):
        self.dismiss()
