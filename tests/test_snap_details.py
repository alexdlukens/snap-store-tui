"""Details-card accuracy tests for :class:`SnapScreen`."""

from __future__ import annotations

from datetime import UTC, datetime

import humanize
import pytest
from snap_python.schemas.store.info import InfoResponse
from textual.app import App, ComposeResult
from textual.widgets import Label, Static

from store_tui.screens.snap import SnapScreen
from store_tui.snapd import InstalledState

LARGEST_DOWNLOAD = 9_000_000
HOLD = datetime(2025, 5, 1, 12, 0, tzinfo=UTC)


class HostApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Static("host")


def _channel(name: str) -> dict:
    return {
        "architecture": "amd64",
        "name": name,
        "risk": name,
        "track": "latest",
        "released-at": "2025-01-02T03:04:05+00:00",
    }


def _info(channel_map: list[dict]) -> InfoResponse:
    return InfoResponse.model_validate(
        {
            "channel-map": channel_map,
            "name": "demo",
            "snap": {
                "name": "demo",
                "title": "Demo",
                "summary": "A demo snap",
                "description": "Demo description",
                "license": "MIT",
                "store-url": "https://snapcraft.io/demo",
            },
            "snap-id": "demo-id",
        }
    )


def demo_info() -> InfoResponse:
    """Two channel entries whose union is wider than either entry's channel."""
    return _info(
        [
            {
                "channel": _channel("stable"),
                "architectures": ["amd64", "arm64"],
                "base": "core26",
                "type": "app",
                "confinement": "strict",
                "download": {
                    "deltas": [],
                    "size": 1_500_000,
                    "url": "https://example.test/demo_amd64.snap",
                },
            },
            {
                "channel": _channel("candidate"),
                "base": "core24",
                "type": "app",
                "confinement": "strict",
                "download": {
                    "deltas": [],
                    "size": LARGEST_DOWNLOAD,
                    "url": "https://example.test/demo_candidate.snap",
                },
            },
        ]
    )


async def open_details(pilot, info: InfoResponse, state: InstalledState) -> SnapScreen:
    screen = SnapScreen(
        snap_name="demo",
        snap_info=info,
        install_state=state,
        client=None,
    )
    await pilot.app.push_screen(screen)
    await pilot.pause()
    return screen


async def test_details_show_metadata_and_architecture_union(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    app = HostApp()
    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_details(pilot, demo_info(), InstalledState(installed=False))

        assert screen.supported_architectures == ["amd64", "arm64"]
        texts = [str(label.renderable) for label in screen.query(Label)]
        assert "Archs: amd64, arm64" in texts
        assert "Base: core24, core26" in texts
        assert "Type: app" in texts
        assert "Confinement: strict" in texts
        assert f"Download: {humanize.naturalsize(LARGEST_DOWNLOAD)}" in texts
        assert "Supported: ✅ on amd64" in texts
        assert "Installed: ❌" in texts


async def test_details_show_unknown_metadata(monkeypatch) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    info = _info([{"channel": _channel("stable")}])
    app = HostApp()
    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_details(pilot, info, InstalledState(installed=False))

        assert screen.supported_architectures == ["amd64"]
        texts = [str(label.renderable) for label in screen.query(Label)]
        assert "Base: Unknown" in texts
        assert "Type: Unknown" in texts
        assert "Confinement: Unknown" in texts
        assert "Download: Unknown" in texts


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (
            InstalledState(installed=True, version="1.2.3", channel="latest/stable"),
            "Installed: ✅ (1.2.3) · latest/stable",
        ),
        (
            InstalledState(
                installed=True,
                version="1.2.3",
                channel="latest/edge",
                broken="missing dependency",
                hold=HOLD,
            ),
            "Installed: ✅ (1.2.3) · latest/edge · broken · hold",
        ),
        (
            InstalledState(installed=True, version="1.2.3", hold=HOLD),
            "Installed: ✅ (1.2.3) · hold",
        ),
        (InstalledState(installed=False), "Installed: ❌"),
        (
            InstalledState(installed=False, error="connection refused"),
            "Installed: ❓ (could not query snapd)",
        ),
    ],
)
async def test_installed_label_includes_channel_hold_and_broken(
    monkeypatch, state: InstalledState, expected: str
) -> None:
    monkeypatch.setattr(
        "store_tui.screens.snap.get_platform_architecture", lambda: "amd64"
    )
    app = HostApp()
    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_details(pilot, demo_info(), state)
        label = screen.query_one("#is-installed-label", Label)
        assert str(label.renderable) == expected
