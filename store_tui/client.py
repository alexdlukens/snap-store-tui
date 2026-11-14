"""Client construction and small platform helpers."""

from __future__ import annotations

import asyncio
import platform
from typing import Any

from snap_python.client import SnapClient

DEFAULT_STORE_URL = "https://api.snapcraft.io"
DEFAULT_STORE_HEADERS = {"Snap-Device-Series": "16", "X-Ubuntu-Series": "16"}

_ARCHITECTURE_MAP = {
    "x86_64": "amd64",
    "amd64": "amd64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "armhf",
    "armv7": "armhf",
    "armv6l": "armhf",
    "i386": "i386",
    "i486": "i386",
    "i586": "i386",
    "i686": "i386",
    "ppc64le": "ppc64el",
    "s390x": "s390x",
    "riscv64": "riscv64",
}


def create_client(
    *,
    store_base_url: str = DEFAULT_STORE_URL,
    store_headers: dict[str, str] | None = None,
    prompt_for_authentication: bool = True,
) -> SnapClient:
    """Build the SnapClient used by the application.

    No network traffic happens here; requests are only made once the app starts.
    """
    headers = dict(DEFAULT_STORE_HEADERS)
    if store_headers:
        headers.update(store_headers)
    return SnapClient(
        store_base_url=store_base_url,
        version="v2",
        store_headers=headers,
        prompt_for_authentication=prompt_for_authentication,
    )


async def close_client(client: Any) -> None:
    """Close any HTTP clients owned by ``client``, ignoring objects that lack them.

    Tolerant by design: tests and embedders may supply lightweight stand-ins.
    """
    closers = []
    for owner in (client, getattr(client, "store", None)):
        if owner is None:
            continue
        for attribute in ("snapd_client", "store_client"):
            candidate = getattr(owner, attribute, None)
            aclose = getattr(candidate, "aclose", None)
            if callable(aclose):
                closers.append(aclose())
    if closers:
        await asyncio.gather(*closers, return_exceptions=True)


def get_platform_architecture() -> str:
    """Return the current machine architecture using snap store names."""
    machine = platform.machine().lower()
    return _ARCHITECTURE_MAP.get(machine, machine)
