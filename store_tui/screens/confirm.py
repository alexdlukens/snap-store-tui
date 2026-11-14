"""Generic confirmation modal for destructive actions."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Label


class ConfirmScreen(ModalScreen[bool]):
    """Ask the user to confirm; dismisses ``True`` only on explicit confirm."""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        message: str,
        *,
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
    ) -> None:
        super().__init__()
        self.title_text = title
        self.message = message
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label(self.title_text, id="confirm-title"),
            Label(self.message, id="confirm-message"),
            Horizontal(
                Button(self.cancel_label, id="confirm-cancel"),
                Button(
                    self.confirm_label,
                    id="confirm-confirm",
                    variant="error",
                ),
                id="confirm-actions",
            ),
            id="confirm-card",
        )
        yield Footer(show_command_palette=False)

    @on(Button.Pressed, "#confirm-cancel")
    def _cancel(self) -> None:
        self.dismiss(False)

    @on(Button.Pressed, "#confirm-confirm")
    def _confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
