"""Snap details screen."""

from __future__ import annotations

import io
from collections.abc import Iterable
from pathlib import Path

import httpx
import humanize
from PIL import Image
from rich_pixels import Pixels
from snap_python.schemas.common import Media
from snap_python.schemas.store.info import ChannelMapItem, InfoResponse
from textual import work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, Markdown, Static

from store_tui.client import get_platform_architecture
from store_tui.screens.install import InstallScreen
from store_tui.snapd import InstalledState, get_installed_state
from store_tui.widgets.clickable_link import ClickableLink

PLACEHOLDER_ICON = Path(__file__).resolve().parent.parent / "assets" / "placeholder.png"
ICON_SIZE = (16, 16)


def _placeholder_pixels() -> Pixels | None:
    try:
        return Pixels.from_image_path(PLACEHOLDER_ICON, resize=ICON_SIZE)
    except Exception:
        return None


class SnapScreen(ModalScreen[None]):
    BINDINGS = [
        ("escape", "dismiss_screen", "Back"),
        ("q", "dismiss_screen", "Close"),
        ("i", "modify", "Install / Modify"),
    ]

    def __init__(
        self,
        snap_name: str,
        snap_info: InfoResponse,
        install_state: InstalledState | None,
        client,
    ) -> None:
        super().__init__()
        self.snap_name = snap_name
        self.snap_info = snap_info
        self.snap = snap_info.snap
        self.install_state = install_state
        self.client = client

        self.title = self.snap.title or self.snap.name or snap_name
        self.publisher = (
            self.snap.publisher.display_name
            if self.snap.publisher is not None
            else "Unknown publisher"
        )
        self.supported_architectures = self.snap_info.supported_architectures

        placeholder = _placeholder_pixels()
        self.icon_widget = Static(placeholder or "", id="snap-icon")
        self.installed_label = Label(
            "", id="is-installed-label", classes="details-item"
        )

    # ------------------------------------------------------------------ helpers
    def _unique_values(self, values: Iterable[str | None]) -> str:
        unique = sorted({value for value in values if value})
        return ", ".join(unique) or "Unknown"

    def _base(self) -> str:
        return self._unique_values(item.base for item in self.snap_info.channel_map)

    def _type(self) -> str:
        return self._unique_values(item.type for item in self.snap_info.channel_map)

    def _confinement(self) -> str:
        return self._unique_values(
            item.confinement for item in self.snap_info.channel_map
        )

    def _download(self) -> str:
        sizes = [
            item.download.size
            for item in self.snap_info.channel_map
            if item.download is not None
        ]
        return humanize.naturalsize(max(sizes)) if sizes else "Unknown"

    def _channels(self) -> list[ChannelMapItem]:
        return [item for item in self.snap_info.channel_map if item.channel]

    def _last_modified(self) -> str:
        released = [
            item.channel.released_at
            for item in self._channels()
            if item.channel.released_at is not None
        ]
        if not released:
            return "Unknown"
        return humanize.naturaltime(max(released))

    def _icon_url(self) -> str | None:
        media: list[Media] | None = self.snap.media
        if not media:
            return None
        for item in media:
            if item.type == "icon":
                return item.url
        return None

    def set_installed_message(self) -> None:
        state = self.install_state
        if state is None or state.error:
            message = "Installed: ❓ (could not query snapd)"
        elif not state.installed:
            message = "Installed: ❌"
        else:
            version = state.version or (
                f"rev. {state.revision}" if state.revision is not None else "unknown"
            )
            message = f"Installed: ✅ ({version})"
            if state.channel:
                message += f" · {state.channel}"
            if state.broken:
                message += " · broken"
            if state.hold is not None:
                message += " · hold"
        self.installed_label.update(message)

    # ------------------------------------------------------------------ compose
    def compose(self) -> ComposeResult:
        arch = get_platform_architecture()
        supported = "✅" if arch in self.supported_architectures else "❌"
        architectures = ", ".join(self.supported_architectures) or "Unknown"
        license_name = self.snap.license or "unset"

        yield Vertical(
            Horizontal(
                Label(self.title, classes="snap-title"),
                Label(self.publisher, classes="snap-publisher"),
                id="snap-header",
            ),
            Label(self.snap.summary or "", classes="snap-summary"),
            VerticalScroll(
                Horizontal(
                    Vertical(
                        Label("Description", classes="section-title"),
                        Markdown(self.snap.description or "_No description provided._"),
                        classes="snap-description",
                    ),
                    Vertical(
                        self.icon_widget,
                        Label(f"License: {license_name}", classes="details-item"),
                        self.installed_label,
                        Label(
                            f"Supported: {supported} on {arch}", classes="details-item"
                        ),
                        Label(f"Archs: {architectures}", classes="details-item"),
                        Label(f"Base: {self._base()}", classes="details-item"),
                        Label(f"Type: {self._type()}", classes="details-item"),
                        Label(
                            f"Confinement: {self._confinement()}",
                            classes="details-item",
                        ),
                        Label(f"Download: {self._download()}", classes="details-item"),
                        Label(
                            f"Last updated: {self._last_modified()}",
                            classes="details-item",
                        ),
                        ClickableLink(
                            "Store page",
                            self.snap.store_url or "",
                            classes="details-item link",
                        ),
                        ClickableLink(
                            "App Center page",
                            f"snap://{self.snap_name}",
                            classes="details-item link",
                        ),
                        classes="snap-details",
                    ),
                    id="snap-card",
                ),
                id="snap-scroll",
            ),
        )
        yield Footer(show_command_palette=False)

    def on_mount(self) -> None:
        self.set_installed_message()
        if self._icon_url():
            self.load_icon()

    @work(exclusive=True, group="snap-icon")
    async def load_icon(self) -> None:
        url = self._icon_url()
        if not url:
            return
        try:
            async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as http:
                response = await http.get(url)
                response.raise_for_status()
            with Image.open(io.BytesIO(response.content)) as image:
                pixels = Pixels.from_image(image, resize=ICON_SIZE)
        except Exception:
            return
        if self.is_mounted:
            self.icon_widget.update(pixels)

    def action_dismiss_screen(self) -> None:
        self.dismiss(None)

    # ------------------------------------------------------------------ install
    def action_modify(self) -> None:
        self.run_worker(
            self._open_install(), group="modify", name="modify", exclusive=True
        )

    async def _open_install(self) -> None:
        result = await self.app.push_screen(
            InstallScreen(
                snap_info=self.snap_info,
                install_state=self.install_state,
                client=self.client,
            ),
            wait_for_dismiss=True,
        )
        if isinstance(result, InstalledState):
            self.install_state = result
            self.set_installed_message()
        await self.refresh_installed_state()

    async def refresh_installed_state(self) -> None:
        """Re-query snapd after the install screen closes, whatever happened."""
        if self.client is None:
            self.install_state = InstalledState(
                installed=False, error="snapd API not available"
            )
        else:
            self.install_state = await get_installed_state(
                self.client, self.snap_info.name
            )
        if self.is_mounted:
            self.set_installed_message()
