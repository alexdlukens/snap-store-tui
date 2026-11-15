"""Refresh-hold duration picker."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, OptionList
from textual.widgets.option_list import Option

HOLD_CHOICES = (
    ("1d", "1d"),
    ("7d", "7d"),
    ("30d", "30d"),
    ("forever", "Forever"),
    ("unhold", "Remove hold"),
)


class HoldScreen(ModalScreen[str | None]):
    """Choose how long refreshes should be held for one snap.

    Dismisses with ``1d``/``7d``/``30d``/``forever``/``unhold``, or ``None``
    when cancelled.
    """

    TITLE = "Hold refreshes"
    BINDINGS = [("escape", "cancel", "Cancel")]

    DEFAULT_CSS = """
    HoldScreen {
        align: center middle;
    }

    #hold-container {
        width: 56;
        height: auto;
        max-height: 100%;
        padding: 0 1;
        border: round $primary;
        background: $surface;
    }

    #hold-container .screen-title {
        width: 100%;
        height: 1;
        content-align: center middle;
        text-style: bold;
    }

    #hold-container .hold-hint {
        height: auto;
        color: $text-muted;
    }

    #hold-options {
        height: auto;
        max-height: 10;
    }
    """

    def __init__(self, snap_name: str = "") -> None:
        super().__init__()
        self.snap_name = snap_name
        self.option_list = OptionList(
            *[Option(label, id=value) for value, label in HOLD_CHOICES],
            id="hold-options",
        )

    def compose(self) -> ComposeResult:
        title = f"Hold refreshes for {self.snap_name}" if self.snap_name else "Hold"
        yield Vertical(
            Label(title, classes="screen-title"),
            Label(
                "Pause snap refreshes for a day, a week, 30 days, or forever. "
                "A hold can be removed at any time.",
                classes="hold-hint",
            ),
            self.option_list,
            id="hold-container",
        )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.option_list.highlighted = 0
        self.option_list.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    @on(OptionList.OptionSelected, "#hold-options")
    def _selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.dismiss(event.option.id)
