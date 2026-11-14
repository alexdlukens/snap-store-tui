"""A label that opens an allowlisted URL on click without blocking the UI."""

from __future__ import annotations

import subprocess
from contextlib import suppress
from urllib.parse import urlparse

from textual import on, work
from textual.events import Click
from textual.widgets import Label

ALLOWED_SCHEMES = {"http", "https", "snap"}


class ClickableLink(Label):
    def __init__(self, text: str, url: str, *args, **kwargs) -> None:
        super().__init__(text, *args, **kwargs)
        self.url = url
        self._openable = self._is_allowed(url)

    @staticmethod
    def _is_allowed(url: str) -> bool:
        parsed = urlparse(url)
        return parsed.scheme in ALLOWED_SCHEMES and bool(parsed.netloc or parsed.path)

    @on(Click)
    def on_link_clicked(self) -> None:
        if not self._openable:
            return
        self._open_in_background()

    @work(thread=True, group="open-url")
    def _open_in_background(self) -> None:
        try:
            self.app.open_url(self.url)
        except Exception:
            with suppress(OSError):
                subprocess.Popen(
                    ["xdg-open", self.url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                )
