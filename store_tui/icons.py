"""Shared icon download, render cache, and display sizing.

The main preview and the snap details screen render icons at different sizes,
but they must share the network cache so opening a details page never downloads
an icon the preview already fetched. Both screens size their icon to the area
available to it, so renders are cached per requested pixel size.
"""

from __future__ import annotations

import asyncio
import io
from collections import OrderedDict

import httpx
from PIL import Image
from rich_pixels import Pixels
from textual.widget import Widget

IconSize = tuple[int, int]
IconCells = tuple[int, int]

# Each resize step produces a new (url, size) render; keep the cache bounded.
MAX_CACHED_RENDERS = 128


def fit_icon_cells(
    max_width: int, max_height: int, aspect: float | None = None
) -> IconCells:
    """Largest ``(columns, rows)`` icon that fits, preserving the image aspect.

    Terminal cells are roughly twice as tall as they are wide and rich-pixels
    maps one image pixel to one cell column and two image pixels to one cell
    row, so a square image needs twice as many columns as rows.
    """
    width = max(1, int(max_width))
    height = max(1, int(max_height))
    ratio = aspect if aspect and aspect > 0 else 1.0
    columns = min(width, max(1, round(2 * height * ratio)))
    rows = max(1, min(height, round(columns / (2 * ratio))))
    return columns, rows


def pixels_for_cells(cells: IconCells) -> IconSize:
    """Pixel dimensions that fill ``cells`` when rendered by rich-pixels."""
    return cells[0], cells[1] * 2


def padding_cells(widget: Widget) -> tuple[int, int]:
    """Return ``(horizontal, vertical)`` padding of a widget in terminal cells."""
    padding = widget.styles.padding
    return (
        padding.left + padding.right,
        padding.top + padding.bottom,
    )


class IconCache:
    """Download each icon once; render it per requested pixel size."""

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout
        self._bytes: dict[str, bytes | None] = {}
        self._aspects: dict[str, float | None] = {}
        self._pixels: OrderedDict[tuple[str, IconSize], Pixels | None] = OrderedDict()
        self._tasks: dict[str, asyncio.Task[bytes | None]] = {}

    def cached_pixels(self, url: str, size: IconSize) -> Pixels | None:
        return self._pixels.get((url, size))

    def has_bytes(self, url: str) -> bool:
        """Whether the icon download has finished, successfully or not."""
        return url in self._bytes

    def aspect(self, url: str) -> float | None:
        """Pixel width / height of a downloaded icon, if it can be decoded."""
        if url in self._aspects:
            return self._aspects[url]
        data = self._bytes.get(url)
        if data is None:
            return None
        aspect: float | None = None
        try:
            with Image.open(io.BytesIO(data)) as image:
                width, height = image.size
            if width and height:
                aspect = width / height
        except Exception:
            aspect = None
        self._aspects[url] = aspect
        return aspect

    def render_cached(self, url: str, size: IconSize) -> Pixels | None:
        """Render an already downloaded icon; no-op before the download lands."""
        key = (url, size)
        if key in self._pixels:
            self._pixels.move_to_end(key)
            return self._pixels[key]
        data = self._bytes.get(url)
        if data is None:
            return None
        try:
            with Image.open(io.BytesIO(data)) as image:
                pixels = Pixels.from_image(image, resize=size)
        except Exception:
            pixels = None
        self._pixels[key] = pixels
        self._pixels.move_to_end(key)
        while len(self._pixels) > MAX_CACHED_RENDERS:
            self._pixels.popitem(last=False)
        return pixels

    async def get_bytes(self, url: str) -> bytes | None:
        if url in self._bytes:
            return self._bytes[url]
        task = self._tasks.get(url)
        if task is None:
            task = asyncio.create_task(self._download_and_store(url))
            self._tasks[url] = task
            task.add_done_callback(lambda _: self._tasks.pop(url, None))
        return await asyncio.shield(task)

    async def _download_and_store(self, url: str) -> bytes | None:
        try:
            data = await self._download(url)
        except Exception:
            data = None
        self._bytes[url] = data
        return data

    async def _download(self, url: str) -> bytes:
        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True
        ) as http:
            response = await http.get(url)
            response.raise_for_status()
            return response.content

    async def close(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
