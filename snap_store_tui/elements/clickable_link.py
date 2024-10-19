import webbrowser

from textual import on
from textual.events import Click
from textual.widgets import Label


class ClickableLink(Label):
    def __init__(self, text: str, url: str, *args, **kwargs) -> None:
        super().__init__(text, *args, **kwargs)
        self.url = url

    @on(Click)
    def on_link_clicked(self):
        # trigger system url handler
        webbrowser.open(self.url, new=2)
