"""Pure channel grouping, ordering, and label helpers for the install screen.

Everything here works on plain ``ChannelMapItem`` values and strings, with no
Textual widgets, app state, or snapd calls, so the selection rules can be
unit-tested without a running application.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import UTC, datetime

import humanize
from snap_python.schemas.store.info import ChannelMapItem

RISK_ORDER: tuple[str, ...] = ("stable", "candidate", "beta", "edge")
"""Canonical risk ordering, most stable first."""

MODES: tuple[str, ...] = ("strict", "classic", "devmode", "jailmode")
"""Install modes offered by the UI, in display order."""

MODE_LABELS: dict[str, str] = {
    "strict": "Strict (recommended)",
    "classic": "Classic",
    "devmode": "Devmode",
    "jailmode": "Jailmode",
}

MODE_HINTS: dict[str, str] = {
    "strict": "Strict: confined by the snap sandbox with only its declared interfaces.",
    "classic": "Classic: runs without sandboxing and gets full system access.",
    "devmode": "Devmode: sandboxed, but policy violations are logged, not blocked.",
    "jailmode": "Jailmode: forces strict confinement even for classic snaps.",
}

UNKNOWN = "Unknown"

_RELEASE_EPOCH = datetime.min.replace(tzinfo=UTC)
_NATURAL_SPLIT = re.compile(r"(\d+)")


def channel_label(item: ChannelMapItem) -> str:
    """Return the canonical ``track/risk`` label (e.g. ``latest/stable``)."""
    return f"{item.channel.track}/{item.channel.name}"


def split_channel(value: str | None) -> tuple[str | None, str | None]:
    """Split an installed channel string into ``(track, risk)``.

    Bare risk names such as ``edge`` (which snapd may report) yield a
    ``None`` track, while other bare values are treated as a track.
    """
    if not value:
        return (None, None)
    track, separator, risk = value.partition("/")
    if separator:
        return (track or None, risk or None)
    if value in RISK_ORDER:
        return (None, value)
    return (value, None)


def released_sort_key(item: ChannelMapItem) -> datetime:
    """Sort key for release dates; unknown dates sort last when reversed."""
    released = item.channel.released_at
    return _RELEASE_EPOCH if released is None else released


def channels_for_architecture(
    channel_map: Iterable[ChannelMapItem], architecture: str
) -> list[ChannelMapItem]:
    """Return channel map entries released for ``architecture``."""
    return [
        item
        for item in channel_map
        if item.channel is not None and item.channel.architecture == architecture
    ]


def group_by_track(
    items: Iterable[ChannelMapItem],
) -> dict[str, list[ChannelMapItem]]:
    """Group channel entries by track, preserving input order per track."""
    grouped: dict[str, list[ChannelMapItem]] = {}
    for item in items:
        grouped.setdefault(item.channel.track, []).append(item)
    return grouped


def natural_key(value: str) -> tuple[tuple[int, int | str], ...]:
    """Natural sort key so ``2.0`` sorts before ``10.0`` and ``beta``."""
    parts: list[tuple[int, int | str]] = []
    for part in _NATURAL_SPLIT.split(value):
        if not part:
            continue
        parts.append((0, int(part)) if part.isdigit() else (1, part.lower()))
    return tuple(parts)


def _newest_release(items: list[ChannelMapItem]) -> datetime | None:
    dates = [
        item.channel.released_at
        for item in items
        if item.channel.released_at is not None
    ]
    return max(dates) if dates else None


def order_tracks(items: Iterable[ChannelMapItem]) -> list[str]:
    """Order track names for the Track pane.

    ``latest`` always comes first. Remaining tracks are ordered by their newest
    release date, descending; tracks without any release dates fall back to a
    natural alphabetical order after the dated tracks.
    """
    all_items = list(items)
    tracks = list(dict.fromkeys(item.channel.track for item in all_items))

    head = ["latest"] if "latest" in tracks else []
    remaining = [track for track in tracks if track != "latest"]

    dated: dict[str, datetime] = {}
    undated: list[str] = []
    for track in remaining:
        released = _newest_release(
            [item for item in all_items if item.channel.track == track]
        )
        if released is None:
            undated.append(track)
        else:
            dated[track] = released

    ordered_dated = sorted(dated, key=lambda track: dated[track], reverse=True)
    return head + ordered_dated + sorted(undated, key=natural_key)


def risks_for_track(
    items: Iterable[ChannelMapItem], track: str
) -> list[ChannelMapItem]:
    """Return the risks present in ``track`` in canonical stable→edge order."""

    def rank(item: ChannelMapItem) -> tuple[int, str]:
        risk = item.channel.risk or item.channel.name
        if risk in RISK_ORDER:
            return (RISK_ORDER.index(risk), risk)
        return (len(RISK_ORDER), risk)

    in_track = [item for item in items if item.channel.track == track]
    return sorted(in_track, key=rank)


def version_text(item: ChannelMapItem) -> str:
    """Best available version string for a channel entry."""
    if item.version:
        return item.version
    if item.revision is not None:
        return f"rev {item.revision}"
    return UNKNOWN


def risk_label(item: ChannelMapItem) -> str:
    """Return ``risk · version`` as shown in the Risk pane."""
    return f"{item.channel.name} · {version_text(item)}"


def risk_entry_label(item: ChannelMapItem, installed_channel: str | None) -> str:
    """Return a risk pane label, marking the currently installed channel."""
    marker = "● " if installed_channel == channel_label(item) else ""
    return f"{marker}{risk_label(item)}"


def mode_entry_label(mode: str, selected: bool) -> str:
    """Return a mode list label with a filled or hollow selection marker."""
    if mode not in MODE_LABELS:
        raise ValueError(f"unknown install mode: {mode!r}")
    return f"{'●' if selected else '○'} {MODE_LABELS[mode]}"


def default_track(
    items: Iterable[ChannelMapItem],
    installed_channel: str | None = None,
    preferred_track: str | None = None,
) -> str | None:
    """Pick the initially selected track.

    The installed channel's track wins when it is present. Otherwise the
    snap's store default track is used when available, falling back to the
    newest track according to :func:`order_tracks`.
    """
    all_items = list(items)
    tracks = order_tracks(all_items)
    if not tracks:
        return None

    installed_track, _ = split_channel(installed_channel)
    if installed_track in tracks:
        return installed_track
    if preferred_track in tracks:
        return preferred_track
    return tracks[0]


def default_risk(
    items: Iterable[ChannelMapItem],
    track: str | None,
    installed_channel: str | None = None,
) -> str | None:
    """Pick the initially selected risk for ``track``.

    The installed risk wins when the installed channel is on this track,
    otherwise ``stable`` when present, otherwise the newest release in the
    track. Ties fall back to the canonical risk order.
    """
    if track is None:
        return None
    in_track = risks_for_track(items, track)
    if not in_track:
        return None

    risks = {item.channel.name for item in in_track}
    installed_track, installed_risk = split_channel(installed_channel)
    if installed_risk in risks and installed_track in (None, track):
        return installed_risk
    if "stable" in risks:
        return "stable"

    newest = max(
        in_track,
        key=lambda item: (
            item.channel.released_at is not None,
            released_sort_key(item),
        ),
    )
    return newest.channel.name


def find_channel(
    items: Iterable[ChannelMapItem], track: str | None, risk: str | None
) -> ChannelMapItem | None:
    """Return the entry for ``track``/``risk`` if it exists."""
    if track is None or risk is None:
        return None
    for item in items:
        if item.channel.track == track and item.channel.name == risk:
            return item
    return None


def default_mode(channel: ChannelMapItem | None) -> str:
    """Initial install mode: Classic for classic snaps, otherwise Strict."""
    if channel is not None and channel.confinement == "classic":
        return "classic"
    return "strict"


def mode_flags(mode: str) -> dict[str, bool]:
    """Map an install mode to the boolean snapd install flags.

    Dangerous is intentionally absent: the UI never offers it because snapd
    only honours it for unasserted local sideloads.
    """
    if mode not in MODE_LABELS:
        raise ValueError(f"unknown install mode: {mode!r}")
    return {
        "classic": mode == "classic",
        "devmode": mode == "devmode",
        "jailmode": mode == "jailmode",
    }


def format_size(item: ChannelMapItem) -> str:
    """Humanized download size, or ``Unknown`` when the store omits it."""
    download = item.download
    if download is None or not download.size:
        return UNKNOWN
    return humanize.naturalsize(int(download.size))


def format_released(released: datetime | None) -> str:
    """Humanized plus absolute release date, or ``Unknown``."""
    if released is None:
        return UNKNOWN
    absolute = released.astimezone(UTC).strftime("%Y-%m-%d")
    return f"{humanize.naturaltime(released)} ({absolute})"


def release_rows(item: ChannelMapItem) -> list[tuple[str, str]]:
    """Aligned key/value rows describing a channel release."""
    revision = UNKNOWN if item.revision is None else str(item.revision)
    return [
        ("Version", version_text(item)),
        ("Revision", revision),
        ("Size", format_size(item)),
        ("Released", format_released(item.channel.released_at)),
        ("Confinement", item.confinement or UNKNOWN),
    ]
