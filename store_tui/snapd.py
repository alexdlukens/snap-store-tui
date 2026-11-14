"""Lenient snapd access.

pysnap 0.1.7 validates installed snaps against a closed list of bases
(core16..core24, bare); modern snapd reports bases such as ``core26`` and
``snaps.list_installed_snaps()`` then raises ValidationError. This module talks
to the snapd HTTP API directly and reads every field defensively.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InstalledState:
    installed: bool
    version: str | None = None
    revision: int | str | None = None
    channel: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class InstalledSnapRow:
    name: str
    summary: str = ""
    channel: str | None = None
    version: str | None = None


class SnapdError(RuntimeError):
    """A snapd request could not be completed."""


def _safe_str(value: Any) -> str:
    try:
        text = str(value)
    except Exception:
        return f"<{type(value).__name__} with unprintable message>"
    return text or type(value).__name__


def _status_code(value: Any) -> int | None:
    status = getattr(value, "status_code", None)
    return status if isinstance(status, int) else None


def _error_status(error: BaseException) -> int | None:
    response = getattr(error, "response", None)
    return _status_code(response) if response is not None else None


def _envelope(response: Any) -> dict | None:
    try:
        data = response.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = _safe_str(value)
    return text or None


def _channel_of(entry: dict) -> str | None:
    return _optional_str(entry.get("tracking-channel") or entry.get("channel"))


async def get_installed_state(client: Any, name: str) -> InstalledState:
    """Return the installed state of ``name`` without raising."""
    try:
        response = await client.request("GET", f"snaps/{name}")
    except Exception as error:
        if _error_status(error) == 404:
            return InstalledState(installed=False)
        return InstalledState(installed=False, error=_safe_str(error))

    status = _status_code(response)
    if status == 404:
        return InstalledState(installed=False)
    if status is not None and not 200 <= status < 300:
        return InstalledState(installed=False, error=f"snapd returned HTTP {status}")

    envelope = _envelope(response)
    if envelope is None:
        return InstalledState(installed=False, error="unexpected response from snapd")
    if envelope.get("type") == "error":
        return InstalledState(
            installed=False,
            error=_optional_str(envelope.get("status")) or "snapd returned an error",
        )
    envelope_status = envelope.get("status-code")
    if isinstance(envelope_status, int) and not 200 <= envelope_status < 300:
        return InstalledState(
            installed=False, error=f"snapd returned HTTP {envelope_status}"
        )
    result = envelope.get("result")
    if not isinstance(result, dict):
        return InstalledState(installed=False, error="snapd returned no snap data")
    result_name = result.get("name")
    if not isinstance(result_name, str) or not result_name:
        return InstalledState(installed=False, error="snapd returned no snap name")

    version = _optional_str(result.get("version"))
    revision = result.get("revision")
    channel = _channel_of(result)
    return InstalledState(
        installed=True,
        version=version,
        revision=revision if isinstance(revision, int | str) else None,
        channel=channel,
    )


async def list_installed(client: Any) -> list[InstalledSnapRow]:
    """List installed snaps, tolerating unknown fields and missing values."""
    try:
        response = await client.request("GET", "snaps")
    except Exception as error:
        raise SnapdError(
            f"could not list installed snaps: {_safe_str(error)}"
        ) from error

    status = _status_code(response)
    if status is not None and not 200 <= status < 300:
        raise SnapdError(f"snapd returned HTTP {status}")

    envelope = _envelope(response)
    result = envelope.get("result") if envelope is not None else None
    if not isinstance(result, list):
        raise SnapdError("unexpected response from snapd")

    rows: list[InstalledSnapRow] = []
    for entry in result:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        rows.append(
            InstalledSnapRow(
                name=name,
                summary=_optional_str(entry.get("summary")) or "",
                channel=_channel_of(entry),
                version=_optional_str(entry.get("version")),
            )
        )
    rows.sort(key=lambda row: row.name)
    return rows
