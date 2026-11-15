"""Tests for the external URL launcher chain, with no real processes."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from store_tui import launcher
from store_tui.launcher import LaunchResult


class FakeProcess:
    """Stand-in for ``subprocess.Popen`` with scripted communicate() results."""

    def __init__(
        self,
        argv: list[str],
        *,
        returncode: int = 0,
        stderr: str = "",
        timeout_first_call: bool = False,
    ) -> None:
        self.argv = argv
        self.returncode = returncode
        self.stderr = None
        self.calls = 0
        self.killed = False
        self._stderr = stderr
        self._timeout_first_call = timeout_first_call

    def communicate(self, timeout=None):
        self.calls += 1
        if self._timeout_first_call and self.calls == 1:
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return "", self._stderr

    def kill(self) -> None:
        self.killed = True


def fake_popen(monkeypatch, responses):
    """Install a Popen double; ``responses`` maps argv[0] to FakeProcess kwargs."""
    spawned: list[tuple[list[str], dict, FakeProcess]] = []

    def popen(argv, **kwargs):
        process = FakeProcess(argv, **responses.get(argv[0], {}))
        spawned.append((argv, kwargs, process))
        return process

    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    return spawned


def assert_isolated_spawn(kwargs: dict) -> None:
    assert kwargs == {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.PIPE,
        "text": True,
        "start_new_session": True,
    }


def allow_app_center_handler(
    monkeypatch, desktop_id: str = "snap-store_snap-store.desktop"
) -> None:
    monkeypatch.setattr(launcher, "snap_url_handler", lambda: desktop_id)


def completed(stdout: str, returncode: int = 0):
    return subprocess.CompletedProcess(
        args=["gio", "mime", "x-scheme-handler/snap"],
        returncode=returncode,
        stdout=stdout,
        stderr="",
    )


def test_snap_url_prefers_app_center_binary(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher, "find_snap_store_binary", lambda: "/snap/bin/snap-store"
    )
    spawned = fake_popen(monkeypatch, {"/snap/bin/snap-store": {"returncode": 0}})

    result = launcher.open_external("snap://firefox")

    assert result == LaunchResult(True, "snap-store")
    [(argv, kwargs, _)] = spawned
    assert argv == ["/snap/bin/snap-store", "snap://firefox"]
    assert_isolated_spawn(kwargs)


def test_snap_url_uses_gio_when_app_center_is_absent(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "find_snap_store_binary", lambda: None)
    allow_app_center_handler(monkeypatch)
    spawned = fake_popen(monkeypatch, {"gio": {}})

    result = launcher.open_external("snap://firefox")

    assert result == LaunchResult(True, "gio open")
    assert [argv for argv, _, _ in spawned] == [["gio", "open", "snap://firefox"]]


def test_gio_failure_falls_through_to_xdg_open(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "find_snap_store_binary", lambda: None)
    allow_app_center_handler(monkeypatch)
    spawned = fake_popen(
        monkeypatch,
        {
            "gio": {
                "returncode": 2,
                "stderr": "gio: snap://firefox: Operation not supported\n",
            },
            "xdg-open": {"returncode": 0},
        },
    )

    result = launcher.open_external("snap://firefox")

    assert result == LaunchResult(True, "xdg-open")
    assert [argv[0] for argv, _, _ in spawned] == ["gio", "xdg-open"]


def test_app_center_non_zero_exit_falls_back_to_gio(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher, "find_snap_store_binary", lambda: "/usr/bin/snap-store"
    )
    allow_app_center_handler(monkeypatch)
    spawned = fake_popen(
        monkeypatch,
        {
            "/usr/bin/snap-store": {"returncode": 1, "stderr": "snap-store: error\n"},
            "gio": {},
        },
    )

    result = launcher.open_external("snap://firefox")

    assert result == LaunchResult(True, "gio open")
    assert [argv[0] for argv, _, _ in spawned] == ["/usr/bin/snap-store", "gio"]


def test_zero_exit_with_error_stderr_is_a_failure(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "find_snap_store_binary", lambda: None)
    allow_app_center_handler(monkeypatch)
    spawned = fake_popen(
        monkeypatch,
        {
            "gio": {"returncode": 0, "stderr": "Failed to open: no handler\n"},
            "xdg-open": {"returncode": 0},
        },
    )

    result = launcher.open_external("snap://firefox")

    assert result == LaunchResult(True, "xdg-open")
    assert [argv[0] for argv, _, _ in spawned] == ["gio", "xdg-open"]


def test_all_strategies_fail_without_browser_fallback(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "find_snap_store_binary", lambda: None)
    allow_app_center_handler(monkeypatch)
    spawned = fake_popen(
        monkeypatch,
        {
            "gio": {"returncode": 2, "stderr": "gio: Operation not supported"},
            "xdg-open": {"returncode": 3, "stderr": "xdg-open: no method available"},
        },
    )
    browser = MagicMock()

    result = launcher.open_external("snap://firefox", browser_opener=browser)

    assert result.opened is False
    assert result.opener is None
    assert "gio open" in result.detail
    assert "xdg-open" in result.detail
    assert [argv[0] for argv, _, _ in spawned] == ["gio", "xdg-open"]
    browser.assert_not_called()


def test_fixed_locations_are_used_when_path_is_empty(monkeypatch) -> None:
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        launcher, "_is_executable", lambda path: path == "/snap/bin/snap-store"
    )

    assert launcher.find_snap_store_binary() == "/snap/bin/snap-store"

    monkeypatch.setattr(
        launcher, "_is_executable", lambda path: path == "/usr/bin/app-center"
    )
    assert launcher.find_snap_store_binary() == "/usr/bin/app-center"


def test_fixed_location_feeds_the_launch_chain(monkeypatch) -> None:
    monkeypatch.setattr(launcher.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        launcher,
        "_is_executable",
        lambda path: path == "/usr/bin/snap-store",
    )
    spawned = fake_popen(monkeypatch, {"/usr/bin/snap-store": {}})

    result = launcher.open_external("snap://firefox")

    assert result == LaunchResult(True, "snap-store")
    assert [argv[0] for argv, _, _ in spawned] == ["/usr/bin/snap-store"]


def test_running_app_center_counts_as_launched(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher, "find_snap_store_binary", lambda: "/usr/bin/snap-store"
    )
    spawned = fake_popen(
        monkeypatch, {"/usr/bin/snap-store": {"timeout_first_call": True}}
    )

    result = launcher.open_external("snap://firefox")

    assert result == LaunchResult(True, "snap-store")
    [(*_, process)] = spawned
    assert process.killed is False


def test_helper_timeout_is_killed_and_next_strategy_runs(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "find_snap_store_binary", lambda: None)
    allow_app_center_handler(monkeypatch)
    spawned = fake_popen(
        monkeypatch,
        {"gio": {"timeout_first_call": True}, "xdg-open": {}},
    )

    result = launcher.open_external("snap://firefox")

    assert result == LaunchResult(True, "xdg-open")
    gio_process = spawned[0][2]
    assert gio_process.killed is True
    # communicate() is called again after kill() to reap the child.
    assert gio_process.calls == 2


def test_missing_launcher_binary_is_reported(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "find_snap_store_binary", lambda: None)
    allow_app_center_handler(monkeypatch)

    def popen(argv, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", argv[0])

    monkeypatch.setattr(launcher.subprocess, "Popen", popen)

    result = launcher.open_external("snap://firefox")

    assert result.opened is False
    assert "could not run gio" in result.detail


def test_http_urls_are_delegated_to_browser_opener(monkeypatch) -> None:
    spawned = fake_popen(monkeypatch, {})
    browser = MagicMock()

    result = launcher.open_external("https://snapcraft.io/vlc", browser_opener=browser)

    assert result == LaunchResult(True, "browser")
    browser.assert_called_once_with("https://snapcraft.io/vlc")
    assert spawned == []


def test_http_urls_without_browser_opener_do_not_spawn(monkeypatch) -> None:
    spawned = fake_popen(monkeypatch, {})

    result = launcher.open_external("https://snapcraft.io/vlc")

    assert result.opened is False
    assert "browser opener" in result.detail
    assert spawned == []


def test_browser_opener_failure_is_reported(monkeypatch) -> None:
    spawned = fake_popen(monkeypatch, {})

    def broken(url):
        raise OSError("no display")

    result = launcher.open_external("http://example.com", browser_opener=broken)

    assert result.opened is False
    assert result.opener == "browser"
    assert "no display" in result.detail
    assert spawned == []


def test_empty_url_is_rejected(monkeypatch) -> None:
    spawned = fake_popen(monkeypatch, {})

    result = launcher.open_external("")

    assert result.opened is False
    assert result.detail == "empty url"
    assert spawned == []


@pytest.mark.parametrize(
    "desktop_id",
    [
        "snap-store.desktop",
        "snap-store_snap-store.desktop",
        "app-center.desktop",
        "/usr/share/applications/app-center.desktop",
    ],
)
def test_app_center_handler_ids_are_accepted(desktop_id) -> None:
    assert launcher._is_app_center_handler(desktop_id)


@pytest.mark.parametrize(
    "desktop_id",
    [
        "store-tui.desktop",
        "store-tui_store-tui.desktop",
        "org.gnome.Software.desktop",
        "firefox.desktop",
        "",
        None,
    ],
)
def test_foreign_handlers_are_rejected(desktop_id) -> None:
    assert not launcher._is_app_center_handler(desktop_id)


def test_handler_query_parses_gio_mime_output(monkeypatch) -> None:
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return completed(
            "Default application for “x-scheme-handler/snap”: "
            "snap-store_snap-store.desktop\n"
            "Registered applications:\n"
            "\torg.gnome.Software.desktop\n"
        )

    monkeypatch.setattr(launcher.subprocess, "run", fake_run)

    assert launcher.snap_url_handler() == "snap-store_snap-store.desktop"
    [(argv, kwargs)] = calls
    assert argv == ["gio", "mime", "x-scheme-handler/snap"]
    assert kwargs["env"]["LC_ALL"] == "C"
    assert kwargs["timeout"] == launcher.HANDLER_QUERY_TIMEOUT
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        "garbage\n",
        "Registered applications:\n\tstore-tui.desktop\n",
        "Applicazione predefinita per “x-scheme-handler/snap”: app-center.desktop\n",
        "Default application for “x-scheme-handler/snap”:\n",
    ],
)
def test_unusable_handler_output_yields_none(monkeypatch, stdout) -> None:
    monkeypatch.setattr(launcher.subprocess, "run", lambda *a, **k: completed(stdout))
    assert launcher.snap_url_handler() is None


def test_handler_query_failure_yields_none(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher.subprocess, "run", lambda *a, **k: completed("", returncode=2)
    )
    assert launcher.snap_url_handler() is None

    def missing(*args, **kwargs):
        raise FileNotFoundError(2, "No such file or directory", "gio")

    monkeypatch.setattr(launcher.subprocess, "run", missing)
    assert launcher.snap_url_handler() is None


def test_handler_query_timeout_yields_none(monkeypatch) -> None:
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired("gio", launcher.HANDLER_QUERY_TIMEOUT)

    monkeypatch.setattr(launcher.subprocess, "run", slow)
    assert launcher.snap_url_handler() is None


@pytest.mark.parametrize(
    "handler",
    [
        "store-tui.desktop",
        "store-tui_store-tui.desktop",
        "org.gnome.Software.desktop",
        "firefox.desktop",
    ],
)
def test_foreign_snap_handler_blocks_native_fallbacks(monkeypatch, handler) -> None:
    monkeypatch.setattr(launcher, "find_snap_store_binary", lambda: None)
    allow_app_center_handler(monkeypatch, handler)
    spawned = fake_popen(monkeypatch, {})
    browser = MagicMock()

    result = launcher.open_external("snap://firefox", browser_opener=browser)

    assert result.opened is False
    assert result.opener is None
    assert handler in result.detail
    assert spawned == []
    browser.assert_not_called()


def test_unregistered_snap_handler_blocks_native_fallbacks(monkeypatch) -> None:
    monkeypatch.setattr(launcher, "find_snap_store_binary", lambda: None)
    allow_app_center_handler(monkeypatch, None)
    spawned = fake_popen(monkeypatch, {})

    result = launcher.open_external("snap://firefox")

    assert result.opened is False
    assert "no snap:// handler registered" in result.detail
    assert spawned == []


def test_failed_direct_launch_with_foreign_handler_has_no_fallback(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher, "find_snap_store_binary", lambda: "/usr/bin/snap-store"
    )
    allow_app_center_handler(monkeypatch, "store-tui.desktop")
    spawned = fake_popen(
        monkeypatch,
        {"/usr/bin/snap-store": {"returncode": 1, "stderr": "snap-store: error"}},
    )

    result = launcher.open_external("snap://firefox")

    assert result.opened is False
    assert "store-tui.desktop" in result.detail
    assert "snap-store: snap-store: error" in result.detail
    assert [argv[0] for argv, _, _ in spawned] == ["/usr/bin/snap-store"]


def test_direct_launch_does_not_consult_handler(monkeypatch) -> None:
    monkeypatch.setattr(
        launcher, "find_snap_store_binary", lambda: "/usr/bin/snap-store"
    )

    def unexpected():
        raise AssertionError("handler must not be queried when App Center launched")

    monkeypatch.setattr(launcher, "snap_url_handler", unexpected)
    fake_popen(monkeypatch, {"/usr/bin/snap-store": {}})

    assert launcher.open_external("snap://firefox") == LaunchResult(True, "snap-store")
