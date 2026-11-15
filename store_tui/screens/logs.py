"""Journal viewer for one installed snap's services."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, Static

EMPTY_LOGS = "No logs available (is this a service snap?)"
LOG_LIMIT = 200


def _field(entry: Any, name: str) -> str:
    value = getattr(entry, name, None)
    if value is None and isinstance(entry, dict):
        value = entry.get(name)
    return "" if value is None else str(value)


def format_logs(entries: list[Any] | None) -> str:
    """Render ``timestamp  message`` lines, one journal entry per line."""
    lines: list[str] = []
    for entry in entries or []:
        timestamp = _field(entry, "timestamp")
        message = _field(entry, "message")
        lines.append(f"{timestamp}  {message}".rstrip())
    return "\n".join(lines)


class LogsScreen(ModalScreen[None]):
    """Show the most recent journal lines for a snap."""

    TITLE = "Logs"
    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
    ]

    DEFAULT_CSS = """
    LogsScreen {
        layout: vertical;
        background: $surface;
    }

    #logs-title {
        height: 1;
        padding: 0 1;
        text-style: bold;
    }

    #logs-scroll {
        height: 1fr;
        padding: 0 1;
    }

    #logs-content {
        height: auto;
    }
    """

    def __init__(self, client: Any, name: str) -> None:
        super().__init__()
        self.client = client
        self.snap_name = name
        self.content = Static("Loading logs…", id="logs-content")
        self.title_label = Label(f"Logs for {name}", id="logs-title")

    def compose(self) -> ComposeResult:
        yield self.title_label
        yield VerticalScroll(self.content, id="logs-scroll")
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.run_worker(
            self._load_logs(),
            group="logs",
            name="logs",
            exclusive=True,
        )

    async def _load_logs(self) -> None:
        try:
            entries = await self.client.logs.get_logs(
                names=[self.snap_name], n=LOG_LIMIT
            )
        except Exception as error:
            if self.is_mounted:
                self.content.update(f"Could not read logs: {error}")
            return
        if not self.is_mounted:
            return
        text = format_logs(entries)
        self.content.update(text or EMPTY_LOGS)

    def action_close(self) -> None:
        self.dismiss(None)
