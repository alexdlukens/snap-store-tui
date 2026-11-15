"""Category picker."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, OptionList


class CategoryScreen(ModalScreen[str | None]):
    BINDINGS = [("escape", "dismiss_screen", "Back")]

    def __init__(self, categories: list[str], current: str | None = None) -> None:
        super().__init__()
        self.categories = list(categories)
        self.current = current

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Choose a category", classes="screen-title"),
            OptionList(*self.categories, id="category-list"),
            id="category-container",
        )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        if self.current in self.categories:
            option_list.highlighted = self.categories.index(self.current)
        elif self.categories:
            option_list.highlighted = 0
        option_list.focus()

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    @on(OptionList.OptionSelected)
    def _selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(str(event.option.prompt))
