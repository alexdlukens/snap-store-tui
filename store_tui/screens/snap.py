"""Snap details screen."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import humanize
from rich_pixels import Pixels
from snap_python.schemas.common import Media
from snap_python.schemas.store.info import ChannelMapItem, InfoResponse
from textual import events, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Footer, Label, Markdown, Static

from store_tui.client import get_platform_architecture
from store_tui.icons import (
    IconCache,
    fit_icon_cells,
    padding_cells,
    pixels_for_cells,
)
from store_tui.screens.install import InstallScreen
from store_tui.snapd import InstalledState, get_installed_state
from store_tui.widgets.clickable_link import ClickableLink

PLACEHOLDER_ICON = Path(__file__).resolve().parent.parent / "assets" / "placeholder.png"
FALLBACK_ICON_CELLS = (16, 8)


def _placeholder_pixels(size: tuple[int, int]) -> Pixels | None:
    try:
        return Pixels.from_image_path(PLACEHOLDER_ICON, resize=size)
    except Exception:
        return None


class _IconArea(VerticalScroll):
    """Report viewport size changes so the details icon can re-fit."""

    def on_resize(self, event: events.Resize) -> None:
        self.screen._sync_icon_size()


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
        icon_cache: IconCache | None = None,
    ) -> None:
        super().__init__()
        self.snap_name = snap_name
        self.snap_info = snap_info
        self.snap = snap_info.snap
        self.install_state = install_state
        self.client = client
        self.icon_cache = icon_cache if icon_cache is not None else IconCache()
        self._owns_icon_cache = icon_cache is None

        self.title = self.snap.title or self.snap.name or snap_name
        self.publisher = (
            self.snap.publisher.display_name
            if self.snap.publisher is not None
            else "Unknown publisher"
        )
        self.supported_architectures = self.snap_info.supported_architectures

        placeholder = _placeholder_pixels(pixels_for_cells(FALLBACK_ICON_CELLS))
        self.icon_widget = Static(placeholder or "", id="snap-icon")
        self._icon_cells = FALLBACK_ICON_CELLS
        self._icon_outer = FALLBACK_ICON_CELLS
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
            _IconArea(
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
        self.call_after_refresh(self._sync_icon_size)
        if self._icon_url():
            self.load_icon()

    def _icon_pixel_size(self) -> tuple[int, int]:
        return pixels_for_cells(self._icon_cells)

    def _sync_icon_size(self, force: bool = False) -> None:
        """Fit the icon to the details column and the visible scroll height."""
        if not self.is_mounted:
            return
        details = self.query_one(".snap-details")
        scroll = self.query_one("#snap-scroll")
        horizontal, vertical = padding_cells(self.icon_widget)
        available_width = details.content_size.width - horizontal
        available_height = scroll.content_size.height - vertical
        if available_width <= 0 or available_height <= 0:
            return
        url = self._icon_url()
        aspect = self.icon_cache.aspect(url) if url else None
        cells = fit_icon_cells(available_width, available_height, aspect)
        outer = (cells[0] + horizontal, cells[1] + vertical)
        if cells == self._icon_cells and outer == self._icon_outer and not force:
            return
        self._icon_cells = cells
        self._icon_outer = outer
        self.icon_widget.styles.width = outer[0]
        self.icon_widget.styles.height = outer[1]
        self._render_icon()

    def _render_icon(self) -> None:
        url = self._icon_url()
        size = self._icon_pixel_size()
        pixels = self.icon_cache.render_cached(url, size) if url else None
        self.icon_widget.update(pixels or _placeholder_pixels(size) or "")

    @work(exclusive=True, group="snap-icon")
    async def load_icon(self) -> None:
        url = self._icon_url()
        if not url:
            return
        await self.icon_cache.get_bytes(url)
        if self.is_mounted:
            self.call_after_refresh(self._sync_icon_size, True)

    async def on_unmount(self) -> None:
        if self._owns_icon_cache:
            await self.icon_cache.close()

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
