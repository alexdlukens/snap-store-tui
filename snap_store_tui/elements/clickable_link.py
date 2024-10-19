import webbrowser

from rich.markdown import Link
from textual import on
from textual.events import Click
from textual.widget import Widget
from textual.widgets import Label, Markdown


class ClickableLink(Widget):
    def __init__(self, text: str, url: str, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.text = text
        self.url = url
        # self.content = Link(self.text, self.url)

    def compose(self):
        yield Label(self.text)

    @on(Click)
    def on_link_clicked(self):
        # trigger system url handler
        webbrowser.open(self.url, new=2)
