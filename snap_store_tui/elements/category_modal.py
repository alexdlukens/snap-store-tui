from pathlib import Path

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.widgets import OptionList

CATEGORY_CSS_PATH = Path(__file__).parent.parent / "styles" / "category_modal.tcss"


class CategoryModal(ModalScreen):
    CSS_PATH = CATEGORY_CSS_PATH

    def __init__(
        self, categories: list[tuple[str, str]], current_category: str
    ) -> None:
        super().__init__()
        self.categories = categories
        self.current_category = current_category

    def compose(self) -> ComposeResult:
        option_list = OptionList(
            *self.categories, name="category", id="category_option_list", wrap=False
        )
        yield option_list

    def on_option_list_option_selected(self, option: OptionList.OptionSelected) -> None:
        self.dismiss(option.option.prompt)
