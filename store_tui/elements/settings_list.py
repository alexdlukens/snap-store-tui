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

    def update(self, settings: list[Selection]):
        self._settings = settings
        self.refresh(recompose=True)

    def add_setting(self, setting: Selection):
        self._settings.append(setting)
        self.refresh(recompose=True)

    def compose(self):
        yield SelectionList(*self._settings, id=self.id)
