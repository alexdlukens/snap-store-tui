"""Modal error / traceback viewer."""

from __future__ import annotations

import traceback

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, TextArea


def _safe_str(value: object) -> str:
    try:
        return str(value)
    except Exception:
        return f"<{type(value).__name__} with unprintable message>"


def format_error(error: BaseException | str | object) -> str:
    """Render any error value as text, never raising."""
    if isinstance(error, BaseException):
        try:
            return "".join(
                traceback.format_exception(type(error), error, error.__traceback__)
            )
        except Exception:  # pragma: no cover - defensive
            return f"{type(error).__name__}: {_safe_str(error)}"
    return _safe_str(error)


class ErrorScreen(ModalScreen[None]):
    BINDINGS = [
        ("escape", "dismiss_screen", "Back"),
        ("q", "dismiss_screen", "Close"),
    ]

    def __init__(
        self, error: BaseException | str | object, title: str = "Error"
    ) -> None:
        super().__init__()
        self.error = error
        self.error_title = title
        self.error_text = format_error(error)
        self.title_label = Label(self.error_title, id="error-title")
        self.close_button = Button("Close", variant="error", id="error-close")
        self.text_area = TextArea(
            self.error_text,
            show_line_numbers=True,
            read_only=True,
            id="error-traceback",
        )

    def compose(self) -> ComposeResult:
        yield Vertical(
            Vertical(
                self.title_label,
                self.text_area,
                Horizontal(
                    self.close_button,
                    id="error-actions",
                ),
                id="error-card",
            ),
            id="error-container",
        )

    def on_mount(self) -> None:
        self.text_area.load_text(self.error_text)
        self.text_area.scroll_end(animate=False)
        self.text_area.move_cursor(self.text_area.document.end)
        self.close_button.focus()

    def set_error(self, error: BaseException | str | object, title: str) -> None:
        """Replace the displayed error without pushing another screen."""
        self.error = error
        self.error_title = title
        self.error_text = format_error(error)
        self.title_label.update(title)
        if self.is_mounted:
            self.text_area.load_text(self.error_text)
            self.text_area.scroll_end(animate=False)

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    @on(Button.Pressed, "#error-close")
    def _close(self) -> None:
        self.dismiss(None)
