"""Shared icon cache behavior."""

from __future__ import annotations

import asyncio
from pathlib import Path

from store_tui.icons import IconCache, fit_icon_cells

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

    url = "https://icons.test/alpha.png"
    first = await cache.get_bytes(url)
    again = await cache.get_bytes(url)

    assert first == ICON_BYTES
    assert again is first
    assert calls == [url]
    await cache.close()


async def test_icon_cache_concurrent_callers_share_download(monkeypatch) -> None:
    cache = IconCache()
    calls: list[str] = []

    async def fake_download(self, url: str) -> bytes:
        calls.append(url)
        return ICON_BYTES

    monkeypatch.setattr(IconCache, "_download", fake_download)

    first, second = await asyncio.gather(
        cache.get_bytes("https://icons.test/alpha.png"),
        cache.get_bytes("https://icons.test/alpha.png"),
    )

    assert first == ICON_BYTES
    assert second is first
    assert calls == ["https://icons.test/alpha.png"]
    await cache.close()


def test_fit_icon_cells_bounds_by_width_or_height() -> None:
    assert fit_icon_cells(40, 20) == (40, 20)
    assert fit_icon_cells(40, 10) == (20, 10)
    assert fit_icon_cells(0, 0) == (1, 1)


def test_fit_icon_cells_preserves_image_aspect() -> None:
    # Two image pixels per cell row, so a 2:1 image uses half the rows.
    assert fit_icon_cells(40, 40, 2.0) == (40, 10)
    assert fit_icon_cells(40, 40, 0.5) == (40, 40)


async def test_icon_cache_renders_dynamic_sizes_from_one_download(monkeypatch) -> None:
    cache = IconCache()
    calls: list[str] = []

    async def fake_download(self, url: str) -> bytes:
        calls.append(url)
        return ICON_BYTES

    monkeypatch.setattr(IconCache, "_download", fake_download)

    await cache.get_bytes("https://icons.test/alpha.png")
    assert cache.aspect("https://icons.test/alpha.png") == 1.0

    small = cache.render_cached("https://icons.test/alpha.png", (8, 8))
    large = cache.render_cached("https://icons.test/alpha.png", (64, 64))

    assert small is not None
    assert large is not None
    assert cache.cached_pixels("https://icons.test/alpha.png", (8, 8)) is small
    assert cache.cached_pixels("https://icons.test/alpha.png", (64, 64)) is large
    assert calls == ["https://icons.test/alpha.png"]
    await cache.close()
