"""Install settings selection list."""

from __future__ import annotations

from contextlib import suppress

from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import SelectionList
from textual.widgets.selection_list import Selection


class SettingsList(Widget):
    """Wraps a SelectionList and maps its selected *values* to booleans."""

    def __init__(
        self,
        settings: list[Selection] | None = None,
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes, disabled=disabled)
        self._settings: list[Selection] = list(settings or [])

    def compose(self):
        yield SelectionList[str](id="settings-options")

    def on_mount(self) -> None:
        if self._settings:
            self.update_settings(self._settings)

    def update_settings(self, settings: list[Selection]) -> None:
        """Rebuild the options in place, re-applying initial states."""
        self._settings = list(settings)
        selection_list = self._selection_list()
        if selection_list is None:
            return
        selection_list.clear_options()
        selection_list.add_options(self._settings)
        for setting in self._settings:
            if setting.initial_state and not setting.disabled:
                selection_list.select(setting.value)

    def add_setting(self, setting: Selection) -> None:
        self.update_settings([*self._settings, setting])

    def _selection_list(self) -> SelectionList | None:
        if not self.is_mounted:
            return None
        with suppress(NoMatches):
            return self.query(SelectionList).first()
        return None

    def get_selection_state(self) -> dict[str, bool]:
        """Map each enabled selection value to whether it is selected."""
        if not self.is_mounted:
            return {
                setting.value: bool(setting.initial_state)
                for setting in self._settings
                if not setting.disabled
            }
        selection_list = self._selection_list()
        if selection_list is None:
            return {
                setting.value: bool(setting.initial_state)
                for setting in self._settings
                if not setting.disabled
            }
        selected = set(selection_list.selected)
        return {
            setting.value: setting.value in selected
            for setting in self._settings
            if not setting.disabled
        }
