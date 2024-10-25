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
        self.text_area = TextArea(
            self.error_text, show_line_numbers=True, read_only=True
        )
        self.text_area.scroll_end(duration=0.5)

    def compose(self):
        yield Header()
        yield self.text_area
        yield Button("OK", variant="error")

    @on(Button.Pressed)
    def on_button_pressed(self):
        self.dismiss()
