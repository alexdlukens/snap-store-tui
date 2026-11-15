"""A label that opens an allowlisted URL on click without blocking the UI."""

from __future__ import annotations

from contextlib import suppress
from urllib.parse import urlparse

from textual import on, work
from textual.events import Click
from textual.widgets import Label

from store_tui import launcher

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
        # open_external is synchronous and blocking, hence the thread worker.
        result = launcher.open_external(self.url, browser_opener=self.app.open_url)
        if not result.opened:
            # Never fall back to a browser for snap links: ask App Center to
            # handle them, or tell the user why that was not possible.
            with suppress(Exception):
                self.app.call_from_thread(
                    self.notify,
                    self._failure_message(),
                    severity="warning",
                )

    def _failure_message(self) -> str:
        if urlparse(self.url).scheme == launcher.SNAP_SCHEME:
            return "Could not open App Center — is it installed?"
        return f"Could not open {self.url}"
