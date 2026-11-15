"""Shared icon download and render cache.

The main preview and the snap details screen render icons at different sizes,
but they must share the network cache so opening a details page never downloads
an icon the preview already fetched.
"""

from __future__ import annotations

import asyncio
import io

import httpx
from PIL import Image
from rich_pixels import Pixels

IconSize = tuple[int, int]


class IconCache:
    """Download each icon once; render it per requested cell size."""

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout
        self._bytes: dict[str, bytes | None] = {}
        self._pixels: dict[tuple[str, IconSize], Pixels | None] = {}
        self._tasks: dict[str, asyncio.Task[bytes | None]] = {}

    def cached_pixels(self, url: str, size: IconSize) -> Pixels | None:
        return self._pixels.get((url, size))

    def has_pixels(self, url: str, size: IconSize) -> bool:
        return (url, size) in self._pixels

    async def get_bytes(self, url: str) -> bytes | None:
        if url in self._bytes:
            return self._bytes[url]
        task = self._tasks.get(url)
        if task is None:
            task = asyncio.create_task(self._download_and_store(url))
            self._tasks[url] = task
            task.add_done_callback(lambda _: self._tasks.pop(url, None))
        return await asyncio.shield(task)

    async def get_pixels(self, url: str, size: IconSize) -> Pixels | None:
        key = (url, size)
        if key in self._pixels:
            return self._pixels[key]
        data = await self.get_bytes(url)
        if data is None:
            self._pixels[key] = None
            return None
        try:
            with Image.open(io.BytesIO(data)) as image:
                pixels = Pixels.from_image(image, resize=size)
        except Exception:
            pixels = None
        self._pixels[key] = pixels
        return pixels

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
