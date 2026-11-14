"""Search query input."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Input, Label


class SearchScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Search the Snap Store", classes="screen-title"),
            Input(placeholder="Snap name or keywords", id="search-input"),
            id="search-container",
        )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)
