from textual.widget import Widget
from textual.widgets import SelectionList
from textual.widgets.selection_list import Selection


class SettingsList(Widget):
    def __init__(
        self,
        settings: list[Selection] = None,
        name=None,
        id=None,
        classes=None,
        disabled=False,
    ):
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)

        if settings is None:
            settings = []
        self._settings = settings
        for setting in self._settings:
            assert isinstance(setting, Selection)
        self.selection_list = SelectionList(*self._settings, id=self.id)

    def update(self, settings: list[Selection]):
        self._settings = settings
        for setting in self._settings:
            assert isinstance(setting, Selection)
        self.selection_list = SelectionList(*self._settings, id=self.id)
        self.refresh(recompose=True)

    def add_setting(self, setting: Selection):
        assert isinstance(setting, Selection)
        self._settings.append(setting)
        self.selection_list = SelectionList(*self._settings, id=self.id)
        self.refresh(recompose=True)

    def compose(self):
        yield self.selection_list

    def get_selection_state(self) -> dict[str, bool]:
        result = {k.value: False for k in self._settings if not k.disabled}

        selected_item: Selection
        for selected_item in self.selection_list.selected:
            if selected_item not in self._settings:
                continue
            result[selected_item] = True

        return result
