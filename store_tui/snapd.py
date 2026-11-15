"""Typed snapd access for the UI.

This module is a thin adapter over :class:`snap_python.client.SnapClient`.
0.2.0 accepts arbitrary snap bases (including ``core26``), so the old
hand-rolled HTTP envelope parser is gone; every value below comes from a
validated ``InstalledSnap`` model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from snap_python.schemas.snaps import InstalledSnap, SnapRefreshFailures


@dataclass(frozen=True)
class InstalledState:
    """The installed state of one snap, safe to render in the UI."""

    installed: bool
    version: str | None = None
    revision: int | str | None = None
    channel: str | None = None
    error: str | None = None
    confinement: str | None = None
    size: int | None = None
    install_date: datetime | None = None
    hold: datetime | None = None
    gating_hold: datetime | None = None
    refresh_inhibit: datetime | None = None
    broken: str | None = None
    trymode: bool = False
    devmode: bool = False
    status: str | None = None
    refresh_failures: SnapRefreshFailures | None = None


@dataclass(frozen=True)
class InstalledSnapRow:
    """One installed snap, including the fields the management screen needs."""

    name: str
    summary: str = ""
    version: str | None = None
    revision: int | str | None = None
    channel: str | None = None
    confinement: str | None = None
    size: int | None = None
    install_date: datetime | None = None
    hold: datetime | None = None
    gating_hold: datetime | None = None
    refresh_inhibit: datetime | None = None
    broken: str | None = None
    trymode: bool = False
    devmode: bool = False
    status: str | None = None
    grade: str | None = None
    cohort_key: str | None = None
    tracks: tuple[str, ...] = ()
    components: tuple[str, ...] = ()
    refresh_failures: SnapRefreshFailures | None = None
    raw: InstalledSnap | None = field(default=None, repr=False, compare=False)


class SnapdError(RuntimeError):
    """A snapd request could not be completed."""


def _safe_str(value: Any) -> str:
    try:
        text = str(value)
    except Exception:
        return f"<{type(value).__name__} with unprintable message>"
    return text or type(value).__name__


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = _safe_str(value)
    return text or None


def _confinement_of(snap: InstalledSnap) -> str | None:
    confinement = snap.confinement
    if confinement is None:
        return None
    return _optional_str(getattr(confinement, "value", confinement))


def _channel_of(snap: InstalledSnap) -> str | None:
    return _optional_str(snap.tracking_channel or snap.channel)


def _refresh_inhibit_of(snap: InstalledSnap) -> datetime | None:
    inhibit = snap.refresh_inhibit
    return None if inhibit is None else inhibit.proceed_time


def _components_of(snap: InstalledSnap) -> tuple[str, ...]:
    return tuple(
        component.name
        for component in snap.components
        if getattr(component, "name", None)
    )


def row_from_installed(snap: InstalledSnap) -> InstalledSnapRow:
    """Map a validated snapd model to the UI row."""
    return InstalledSnapRow(
        name=snap.name or "",
        summary=snap.summary or "",
        version=_optional_str(snap.version),
        revision=snap.revision,
        channel=_channel_of(snap),
        confinement=_confinement_of(snap),
        size=snap.installed_size,
        install_date=snap.install_date,
        hold=snap.hold,
        gating_hold=snap.gating_hold,
        refresh_inhibit=_refresh_inhibit_of(snap),
        broken=snap.broken,
        trymode=bool(snap.trymode),
        devmode=bool(snap.devmode),
        status=snap.status,
        grade=snap.grade,
        cohort_key=snap.cohort_key,
        tracks=tuple(snap.tracks or ()),
        components=_components_of(snap),
        refresh_failures=snap.refresh_failures,
        raw=snap,
    )


def state_from_installed(snap: InstalledSnap | None) -> InstalledState:
    if snap is None:
        return InstalledState(installed=False)
    row = row_from_installed(snap)
    return InstalledState(
        installed=True,
        version=row.version,
        revision=row.revision,
        channel=row.channel,
        confinement=row.confinement,
        size=row.size,
        install_date=row.install_date,
        hold=row.hold,
        gating_hold=row.gating_hold,
        refresh_inhibit=row.refresh_inhibit,
        broken=row.broken,
        trymode=row.trymode,
        devmode=row.devmode,
        status=row.status,
        refresh_failures=row.refresh_failures,
    )


async def get_installed_state(client: Any, name: str) -> InstalledState:
    """Return the installed state of ``name`` without raising.

    ``snaps.get_installed_snap()`` returns ``None`` only for HTTP 404; every
    other error is reported through ``InstalledState.error``.
    """
    try:
        snap = await client.snaps.get_installed_snap(name)
    except Exception as error:
        return InstalledState(installed=False, error=_safe_str(error))
    return state_from_installed(snap)


async def list_installed(
    client: Any, *, select: str | None = None
) -> list[InstalledSnapRow]:
    """List installed snaps, optionally including inactive revisions."""
    try:
        response = await client.snaps.list_installed_snaps(select=select)
    except Exception as error:
        raise SnapdError(
            f"could not list installed snaps: {_safe_str(error)}"
        ) from error

    result = getattr(response, "result", None)
    if not isinstance(result, list):
        raise SnapdError("unexpected response from snapd while listing snaps")

    rows = [row_from_installed(snap) for snap in result if getattr(snap, "name", None)]
    rows.sort(key=lambda row: row.name)
    return rows


async def is_snap_installed(client: Any, name: str) -> bool:
    """Return whether ``name`` is installed, raising ``SnapdError`` on failure."""
    try:
        return bool(await client.snaps.is_snap_installed(name))
    except Exception as error:
        raise SnapdError(
            f"could not check whether {name} is installed: {_safe_str(error)}"
        ) from error


async def list_revisions(client: Any, name: str) -> list[InstalledSnapRow]:
    """Return every revision snapd knows for ``name``, newest first."""
    try:
        response = await client.snaps.list_installed_snaps(select="all", snaps=[name])
    except Exception as error:
        raise SnapdError(
            f"could not list revisions for {name}: {_safe_str(error)}"
        ) from error

    result = getattr(response, "result", None)
    if not isinstance(result, list):
        raise SnapdError(f"unexpected response from snapd for {name} revisions")

    rows = [row_from_installed(snap) for snap in result if getattr(snap, "name", None)]
    rows.sort(key=_revision_sort_key, reverse=True)
    return rows


def _revision_sort_key(row: InstalledSnapRow) -> tuple[int, str]:
    try:
        revision = int(row.revision)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        revision = -1
    return revision, row.status or ""
