"""Progress bar paired with a status message."""

from __future__ import annotations

from contextlib import suppress

from textual.containers import Horizontal
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Label, ProgressBar


class ProgressBarWithMessage(Widget):
    def compose(self):
        yield Horizontal(
            ProgressBar(
                total=100,
                show_eta=False,
                show_percentage=False,
                id="install-progress-bar",
            ),
            Label("", classes="progress-message"),
            classes="progress-row",
        )

    def update_progress(
        self, done: int | float, total: int | float | None, message: str
    ) -> None:
        """Update bar and message without assuming children still exist.

        Textual 0.89.1 crashes when a ``ProgressBar`` transitions between
        indeterminate (``total=None``) and determinate mode, so the bar always
        stays determinate; an unknown total paints an empty bar and the message
        carries the status.
        """
        if not self.is_mounted:
            return
        bar = self._first(ProgressBar)
        if bar is not None:
            if total is None or total <= 0:
                bar.update(total=1, progress=0)
            else:
                bar.update(total=total, progress=min(done, total))
        label = self._first(Label)
        if label is not None:
            label.update(message)

    def _first(self, widget_type):
        with suppress(NoMatches):
            return self.query(widget_type).first()
        return None
