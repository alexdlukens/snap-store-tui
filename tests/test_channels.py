"""Unit tests for the pure channel rules used by the install screen."""

from __future__ import annotations

import pathlib
from datetime import UTC, datetime

import humanize
import pytest
from snap_python.schemas.store.info import ChannelMapItem, InfoResponse

from store_tui.channels import (
    channel_label,
    channels_for_architecture,
    default_mode,
    default_risk,
    default_track,
    find_channel,
    format_released,
    format_size,
    group_by_track,
    mode_entry_label,
    mode_flags,
    natural_key,
    order_tracks,
    release_rows,
    risk_entry_label,
    risk_label,
    risks_for_track,
    split_channel,
)

DATA_DIR = pathlib.Path(__file__).parent / "data"
MULTI = InfoResponse.model_validate_json(
    (DATA_DIR / "snap_info_response_multi_track.json").read_text()
)


def amd64_items() -> list[ChannelMapItem]:
    return channels_for_architecture(MULTI.channel_map, "amd64")


def make_item(
    track: str = "latest",
    risk: str = "stable",
    *,
    version: str = "1.0",
    revision: int = 1,
    confinement: str = "strict",
    released_at: str | None = None,
    size: int = 1024,
    architecture: str = "amd64",
) -> ChannelMapItem:
    return ChannelMapItem.model_validate(
        {
            "channel": {
                "architecture": architecture,
                "name": risk,
                "risk": risk,
                "track": track,
                **({"released-at": released_at} if released_at else {}),
            },
            "confinement": confinement,
            "revision": revision,
            "version": version,
            "download": {"deltas": [], "size": size, "url": "https://example/snap"},
        }
    )


def test_channel_label_and_split_channel() -> None:
    item = find_channel(amd64_items(), "latest", "edge")
    assert item is not None
    assert channel_label(item) == "latest/edge"

    assert split_channel("2.0/beta") == ("2.0", "beta")
    assert split_channel("edge") == (None, "edge")
    assert split_channel("2.0") == ("2.0", None)
    assert split_channel(None) == (None, None)


def test_channels_for_architecture_filters_other_arches() -> None:
    items = amd64_items()
    assert len(items) == 7
    assert {item.channel.architecture for item in items} == {"amd64"}
    assert [item.channel.name for item in risks_for_track(items, "1.0")] == ["stable"]


def test_group_by_track() -> None:
    grouped = group_by_track(amd64_items())
    assert list(grouped) == ["latest", "2.0", "1.0"]
    assert len(grouped["latest"]) == 4
    assert [item.channel.name for item in grouped["2.0"]] == ["stable", "beta"]


def test_order_tracks_prefers_latest_then_newest_release() -> None:
    assert order_tracks(amd64_items()) == ["latest", "2.0", "1.0"]

    undated = [
        make_item(track="latest", risk="stable"),
        make_item(track="10.0", risk="stable"),
        make_item(track="2.0", risk="stable"),
        make_item(track="beta-track", risk="stable"),
    ]
    assert order_tracks(undated) == ["latest", "2.0", "10.0", "beta-track"]


def test_order_tracks_puts_undated_after_dated() -> None:
    items = [
        make_item(track="latest", risk="stable", released_at=None),
        make_item(track="old", risk="stable", released_at="2020-01-01T00:00:00Z"),
        make_item(track="a-undated", risk="stable", released_at=None),
        make_item(track="new", risk="stable", released_at="2024-01-01T00:00:00Z"),
    ]
    assert order_tracks(items) == ["latest", "new", "old", "a-undated"]


def test_natural_key_orders_numbers_numerically() -> None:
    assert sorted(["10.0", "2.0", "1.0"], key=natural_key) == ["1.0", "2.0", "10.0"]


def test_risks_for_track_uses_canonical_order() -> None:
    items = amd64_items()
    assert [item.channel.name for item in risks_for_track(items, "latest")] == [
        "stable",
        "candidate",
        "beta",
        "edge",
    ]
    assert [item.channel.name for item in risks_for_track(items, "2.0")] == [
        "stable",
        "beta",
    ]

    unknown = [
        make_item(track="latest", risk="edge"),
        make_item(track="latest", risk="nightly"),
        make_item(track="latest", risk="stable"),
    ]
    assert [item.channel.name for item in risks_for_track(unknown, "latest")] == [
        "stable",
        "edge",
        "nightly",
    ]


def test_risk_labels_include_versions_and_installed_marker() -> None:
    item = find_channel(amd64_items(), "latest", "edge")
    assert item is not None
    assert risk_label(item) == "edge · 2.3.0-dev"
    assert risk_entry_label(item, None) == "edge · 2.3.0-dev"
    assert risk_entry_label(item, "latest/edge") == "● edge · 2.3.0-dev"
    assert risk_entry_label(item, "latest/stable") == "edge · 2.3.0-dev"

    no_version = make_item(version="", revision=42)
    assert risk_label(no_version) == "stable · rev 42"


def test_default_track_prefers_installed_then_store_default_then_newest() -> None:
    items = amd64_items()
    assert default_track(items, "2.0/beta", "latest") == "2.0"
    assert default_track(items, None, "2.0") == "2.0"
    assert default_track(items, None, "missing") == "latest"
    assert default_track(items, None, None) == "latest"
    assert default_track([], None, "latest") is None

    # A bare risk (snapd sometimes reports just "edge") has no track.
    assert default_track(items, "edge", "latest") == "latest"

    # Installed track that no longer exists falls back to the ordering rules.
    dated = [
        make_item(track="latest", risk="stable", released_at="2024-01-01T00:00:00Z"),
        make_item(track="2.0", risk="stable", released_at="2023-01-01T00:00:00Z"),
    ]
    assert default_track(dated, "9.0/stable", None) == "latest"
    assert default_track(dated, "9.0/stable", "2.0") == "2.0"


def test_default_risk_installed_stable_and_newest() -> None:
    items = amd64_items()
    assert default_risk(items, "2.0", "2.0/beta") == "beta"
    assert default_risk(items, "2.0", "latest/edge") == "stable"
    assert default_risk(items, "latest", None) == "stable"
    assert default_risk(items, None) is None
    assert default_risk(items, "missing", None) is None

    newest_only = [
        make_item(track="latest", risk="edge", released_at="2024-01-01T00:00:00Z"),
        make_item(track="latest", risk="candidate", released_at="2023-01-01T00:00:00Z"),
    ]
    assert default_risk(newest_only, "latest", None) == "edge"

    # Unknown dates fall back to the canonical risk order.
    undated = [
        make_item(track="latest", risk="beta"),
        make_item(track="latest", risk="edge"),
    ]
    assert default_risk(undated, "latest", None) == "beta"


def test_find_channel() -> None:
    items = amd64_items()
    item = find_channel(items, "2.0", "beta")
    assert item is not None
    assert item.version == "2.0.5-beta1"
    assert find_channel(items, "2.0", "edge") is None
    assert find_channel(items, None, "stable") is None


def test_mode_entry_label_marker() -> None:
    assert mode_entry_label("strict", True) == "● Strict (recommended)"
    assert mode_entry_label("strict", False) == "○ Strict (recommended)"
    assert mode_entry_label("classic", True) == "● Classic"
    with pytest.raises(ValueError):
        mode_entry_label("dangerous", False)


def test_default_mode_and_mode_flags() -> None:
    classic = find_channel(amd64_items(), "latest", "edge")
    strict = find_channel(amd64_items(), "latest", "stable")
    assert classic is not None and strict is not None
    assert default_mode(classic) == "classic"
    assert default_mode(strict) == "strict"
    assert default_mode(None) == "strict"

    assert mode_flags("strict") == {
        "classic": False,
        "devmode": False,
        "jailmode": False,
    }
    assert mode_flags("classic")["classic"] is True
    assert mode_flags("devmode")["devmode"] is True
    assert mode_flags("jailmode")["jailmode"] is True
    assert "dangerous" not in mode_flags("classic")
    with pytest.raises(ValueError):
        mode_flags("dangerous")


def test_release_rows_and_formatting() -> None:
    item = find_channel(amd64_items(), "latest", "stable")
    assert item is not None
    released = item.channel.released_at
    assert released is not None
    humanized = humanize.naturaltime(released)
    rows = dict(release_rows(item))
    assert rows == {
        "Version": "2.1.0",
        "Revision": "210",
        "Size": "7.3 MB",
        "Released": f"{humanized} (2024-10-01)",
        "Confinement": "strict",
    }

    released = datetime(2024, 10, 1, 12, tzinfo=UTC)
    assert format_released(released).endswith("(2024-10-01)")
    assert format_released(released).startswith(humanize.naturaltime(released))
    assert format_released(None) == "Unknown"
    assert format_size(make_item(size=0)) == "Unknown"

    bare = make_item(version="", revision=7, size=0, confinement="")
    bare = bare.model_copy(update={"download": None})
    rows = dict(release_rows(bare))
    assert rows["Version"] == "rev 7"
    assert rows["Revision"] == "7"
    assert rows["Size"] == "Unknown"
    assert rows["Released"] == "Unknown"
    assert rows["Confinement"] == "Unknown"
