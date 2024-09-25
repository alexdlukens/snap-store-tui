from textual.widgets import Label


class PositionCount(Label):
    def __init__(self, *args, **kwargs):
        self._current_number = 0
        self._total = 0
        super().__init__(*args, **kwargs)

    @property
    def current_number(self):
        return self._current_number

    @current_number.setter
    def current_number(self, num: int):
        self._current_number = num
        self.set_new_text()

    @property
    def total(self):
        return self._total

    @total.setter
    def total(self, num: int):
        self._total = num
        self.set_new_text()

    def set_new_text(self):
        self.update(f"{self._current_number}/{self._total}")
