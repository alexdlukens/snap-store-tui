"""Client construction and small platform helpers."""

from __future__ import annotations

import asyncio
import inspect
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
    "ppc64": "ppc64el",
    "ppc64le": "ppc64el",
    "powerpc": "powerpc",
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
    """Close the HTTP clients owned by ``client``.

    Prefers the 0.2.0 ``SnapClient.close()``; falls back to the individual
    clients for the lightweight stand-ins used by tests and embedders.
    """
    close = getattr(client, "close", None)
    if callable(close):
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
            return
        except Exception:
            # Fall through to the tolerant path below.
            pass

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


async def client_available(client: Any) -> bool:
    """Return True when snapd answered a health probe."""
    is_available = getattr(client, "is_available", None)
    if callable(is_available):
        try:
            return bool(await is_available())
        except Exception:
            return False

    try:
        response = await client.ping()
    except Exception:
        return False
    status = getattr(response, "status_code", None)
    return isinstance(status, int) and 200 <= status < 300


def get_platform_architecture() -> str:
    """Return the current machine architecture using snap store names."""
    machine = platform.machine().lower()
    return _ARCHITECTURE_MAP.get(machine, machine)
