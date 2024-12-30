from textual.containers import Horizontal
from textual.widget import Widget
from textual.widgets import Label, ProgressBar


class ProgressBarWithMessage(Widget):
    def __init__(self, name=None, id=None, classes=None, disabled=False):
        self.progress_bar = ProgressBar(id="progress-bar")
        self.message = Label("", id="progress-bar-message")

        super().__init__(
            self.message, name=name, id=id, classes=classes, disabled=disabled
        )

    def compose(self):
        yield Horizontal(self.progress_bar, self.message)
