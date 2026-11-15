"""Shared icon cache behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path

from store_tui.icons import IconCache

ICON_BYTES = (
    Path(__file__).resolve().parent.parent / "store_tui" / "assets" / "placeholder.png"
).read_bytes()


async def test_icon_cache_downloads_once_per_url(monkeypatch) -> None:
    cache = IconCache()
    calls: list[str] = []

    async def fake_download(self, url: str) -> bytes:
        calls.append(url)
        return ICON_BYTES

    monkeypatch.setattr(IconCache, "_download", fake_download)

    small = await cache.get_pixels("https://icons.test/alpha.png", (4, 4))
    large = await cache.get_pixels("https://icons.test/alpha.png", (16, 16))
    again = await cache.get_pixels("https://icons.test/alpha.png", (4, 4))

    assert small is not None
    assert large is not None
    assert again is small
    assert calls == ["https://icons.test/alpha.png"]
    await cache.close()


async def test_icon_cache_concurrent_callers_share_download(monkeypatch) -> None:
    cache = IconCache()
    calls: list[str] = []

    async def fake_download(self, url: str) -> bytes:
        calls.append(url)
        return ICON_BYTES

    monkeypatch.setattr(IconCache, "_download", fake_download)

    first, second = await asyncio.gather(
        cache.get_pixels("https://icons.test/alpha.png", (4, 4)),
        cache.get_pixels("https://icons.test/alpha.png", (4, 4)),
    )

    assert first is not None
    assert second is not None
    assert calls == ["https://icons.test/alpha.png"]
    await cache.close()
