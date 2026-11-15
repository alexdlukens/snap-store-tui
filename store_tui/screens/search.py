"""Search form: query plus the store filters supported by snap-python 0.2.0."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Footer, Input, Label, Select

from store_tui.search import SearchFilters, SearchRequest

ARCHITECTURES = [
    "amd64",
    "arm64",
    "armhf",
    "i386",
    "ppc64el",
    "powerpc",
    "riscv64",
    "s390x",
]
CONFINEMENTS = [("Strict", "strict"), ("Classic", "classic")]


class SearchScreen(ModalScreen[SearchRequest | None]):
    """Collect a query and optional store filters."""

    BINDINGS = [("escape", "dismiss_screen", "Back")]

    DEFAULT_CSS = """
    SearchScreen {
        align: center middle;
    }

    #search-container {
        width: 72;
        height: auto;
        max-height: 100%;
        padding: 0 1;
        border: round $primary;
        background: $surface;
    }

    #search-container .screen-title {
        width: 100%;
        height: 1;
        content-align: center middle;
        text-style: bold;
    }

    #search-container .search-row {
        height: 1;
    }

    #search-container .field-label {
        width: 14;
        height: 1;
        content-align: left middle;
        padding: 0 1;
        color: $text-muted;
    }

    #search-container Input {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
    }

    #search-container Select {
        width: 1fr;
        height: 1;
    }

    #search-container SelectCurrent {
        height: 1;
        border: none;
        padding: 0 1;
    }

    #search-container #search-featured {
        width: 1fr;
        height: 1;
        border: none;
        padding: 0 1;
    }

    #search-container #search-submit {
        width: 100%;
        min-width: 0;
        height: 1;
        border: none;
    }

    #search-container .search-hint {
        width: 100%;
        height: 1;
        content-align: center middle;
        color: $text-muted;
    }
    """

    PREVIEW_DELAY = 0.3

    def __init__(
        self,
        categories: list[str] | None = None,
        *,
        initial: SearchRequest | None = None,
        on_change: Callable[[SearchRequest], None] | None = None,
    ) -> None:
        super().__init__()
        self.initial = initial or SearchRequest()
        self.on_change = on_change
        self.categories = list(categories or [])
        if (
            self.initial.filters.category
            and self.initial.filters.category not in self.categories
        ):
            self.categories.append(self.initial.filters.category)
        self._preview_timer = None
        self._ready = False

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Search the Snap Store", classes="screen-title"),
            Input(
                value=self.initial.query,
                placeholder="Snap name or keywords",
                id="search-input",
            ),
            self._row(
                "Confinement",
                Select(
                    CONFINEMENTS,
                    prompt="Any",
                    allow_blank=True,
                    value=self._select_value(self.initial.filters.confinement),
                    id="search-confinement",
                ),
            ),
            self._row(
                "Architecture",
                Select(
                    [(arch, arch) for arch in ARCHITECTURES],
                    prompt="Any",
                    allow_blank=True,
                    value=self._select_value(self.initial.filters.architecture),
                    id="search-architecture",
                ),
            ),
            self._row(
                "Category",
                Select(
                    [(category, category) for category in self.categories],
                    prompt="Any",
                    allow_blank=True,
                    value=self._select_value(self.initial.filters.category),
                    id="search-category",
                ),
            ),
            self._row(
                "Publisher",
                Input(
                    value=self.initial.filters.publisher or "",
                    placeholder="Any publisher",
                    id="search-publisher",
                ),
            ),
            self._row(
                "Channel",
                Input(
                    value=self.initial.filters.channel or "",
                    placeholder="Any channel",
                    id="search-channel",
                ),
            ),
            self._row(
                "Name starts",
                Input(
                    value=self.initial.filters.name_startswith or "",
                    placeholder="Any prefix",
                    id="search-name-prefix",
                ),
            ),
            Horizontal(
                Checkbox(
                    "Featured only",
                    value=bool(self.initial.filters.featured),
                    id="search-featured",
                ),
                classes="search-row",
            ),
            Button("Search", variant="primary", id="search-submit"),
            Label(
                "Results update live as you type or change a filter",
                classes="search-hint",
            ),
            id="search-container",
        )
        yield Footer(show_command_palette=False)

    @staticmethod
    def _row(label: str, widget: Input | Select) -> Horizontal:
        return Horizontal(
            Label(label, classes="field-label"),
            widget,
            classes="search-row",
        )

    @staticmethod
    def _select_value(value: str | None):
        return Select.BLANK if value is None else value

    def on_mount(self) -> None:
        self.query_one("#search-input", Input).focus()
        self.call_after_refresh(self._mark_ready)

    def _mark_ready(self) -> None:
        """Ignore value-change messages produced while the form is composed."""
        self._ready = True

    def action_dismiss_screen(self) -> None:
        self._stop_preview()
        self.dismiss(None)

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        self._submit()

    @on(Button.Pressed, "#search-submit")
    def _search_pressed(self, event: Button.Pressed) -> None:
        self._submit()

    @on(Input.Changed)
    @on(Select.Changed)
    @on(Checkbox.Changed)
    def _form_changed(self) -> None:
        self._schedule_preview()

    def _schedule_preview(self) -> None:
        if not self._ready or self.on_change is None:
            return
        self._stop_preview()
        self._preview_timer = self.set_timer(self.PREVIEW_DELAY, self._emit_preview)

    def _stop_preview(self) -> None:
        if self._preview_timer is not None:
            with suppress(Exception):
                self._preview_timer.stop()
            self._preview_timer = None
        self._ready = False

    def _emit_preview(self) -> None:
        self._preview_timer = None
        self._ready = False
        if not self.is_mounted or self.on_change is None:
            return
        request = self._request()
        if not request.is_empty:
            self.on_change(request)

    def _request(self) -> SearchRequest:
        return SearchRequest(
            query=self._text("search-input") or "",
            filters=SearchFilters(
                confinement=self._selected("search-confinement"),
                category=self._selected("search-category"),
                publisher=self._text("search-publisher"),
                architecture=self._selected("search-architecture"),
                channel=self._text("search-channel"),
                name_startswith=self._text("search-name-prefix"),
                featured=(
                    True if self.query_one("#search-featured", Checkbox).value else None
                ),
            ),
        )

    def _submit(self) -> None:
        self._stop_preview()
        request = self._request()
        self.dismiss(None if request.is_empty else request)

    def _text(self, widget_id: str) -> str | None:
        value = self.query_one(f"#{widget_id}", Input).value.strip()
        return value or None

    def _selected(self, widget_id: str) -> str | None:
        select = self.query_one(f"#{widget_id}", Select)
        if select.is_blank():
            return None
        value = select.value
        return None if value is None else str(value)
