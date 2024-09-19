from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import OptionList


class CategoryModal(ModalScreen):
    def __init__(self, categories: list[tuple[str, str]]) -> None:
        super().__init__()
        self.categories = categories

    def compose(self) -> ComposeResult:
        yield OptionList(
            *self.categories,
            name="category",
        )

    def on_option_list_option_selected(self, option: OptionList.OptionSelected) -> None:
        self.dismiss(option.option.prompt)
