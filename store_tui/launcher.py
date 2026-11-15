"""Open external URLs without handing non-http schemes to a web browser.

Textual's ``App.open_url`` delegates to Python's :mod:`webbrowser`, which passes
``snap://<name>`` to the default browser and silently renders a blank page. This
module keeps browsers for ``http``/``https`` and opens everything else through a
native launcher chain, reporting which strategy worked.

The API is synchronous by design: callers must run it off the UI thread (the
clickable link widget uses a ``thread=True`` worker).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.parse import urlparse

#: Schemes that belong to a browser, exactly as before this module existed.
BROWSER_SCHEMES = frozenset({"http", "https"})

#: Give up on a launcher after this many seconds so the worker cannot hang.
LAUNCH_TIMEOUT = 5.0

#: Resolving the registered scheme handler is a quick read, not a launch.
HANDLER_QUERY_TIMEOUT = 2.0

SNAP_SCHEME = "snap"
SNAP_HANDLER_MIME = "x-scheme-handler/snap"

# Only these desktop entries can be trusted to deliver a snap:// deep link to
# App Center itself; see snap_url_handler().
APP_CENTER_HANDLER_PREFIXES = ("snap-store", "app-center")

# PATH lookups first, then the fixed install locations: a GUI app started from
# a TUI may not inherit a login PATH. "appcenter" is only an alias, so it is
# the last candidate.
SNAP_STORE_NAME = "snap-store"
SNAP_STORE_ALIAS = "appcenter"
SNAP_STORE_PATHS = (
    "/snap/bin/snap-store",
    "/usr/bin/snap-store",
    "/usr/bin/app-center",
)

# Stderr hints that a launcher failed even though it exited 0.
_FAILURE_MARKERS = (
    "error",
    "failed",
    "cannot",
    "can't",
    "unable",
    "not found",
    "no such file",
    "not supported",
)


@dataclass(frozen=True)
class LaunchResult:
    """Outcome of :func:`open_external`.

    ``opener`` names the winning strategy (``"snap-store"``, ``"gio open"``,
    ``"xdg-open"`` or ``"browser"``); ``detail`` explains a failure.
    """

    opened: bool
    opener: str | None = None
    detail: str | None = None


def open_external(
    url: str,
    browser_opener: Callable[[str], object] | None = None,
) -> LaunchResult:
    """Open *url* with the best available strategy.

    ``http``/``https`` are handed to *browser_opener* (Textual's
    ``App.open_url``) and never touch the launcher chain. Every other scheme is
    opened natively and is never given to a browser; pass no *browser_opener*
    when the caller has no browser path for them.

    For ``snap://`` the native fallbacks run only when App Center owns the
    scheme: ``gio open`` and ``xdg-open`` report success on spawn, not on
    delivery, so they can "succeed" while routing the link to a browser or even
    back into this app.

    Blocking: run this from a worker thread.
    """
    if not url:
        return LaunchResult(False, None, "empty url")

    scheme = urlparse(url).scheme.lower()
    if scheme in BROWSER_SCHEMES:
        return _open_in_browser(url, browser_opener)

    failures: list[str] = []
    if scheme == SNAP_SCHEME:
        binary = find_snap_store_binary()
        if binary:
            # App Center's desktop entry is ``Exec=snap-store %U``; a running
            # instance can keep it in the foreground, so a timeout after launch
            # counts as success and the process is left alone.
            ok, detail = _run([binary, url], tolerate_running=True)
            if ok:
                return LaunchResult(True, "snap-store")
            failures.append(f"snap-store: {detail}")
        handler = snap_url_handler()
        if not _is_app_center_handler(handler):
            failures.append(_handler_rejection(handler))
            return LaunchResult(False, None, "; ".join(failures))

    for opener, argv in _fallback_strategies(url):
        ok, detail = _run(argv, tolerate_running=False)
        if ok:
            return LaunchResult(True, opener)
        failures.append(f"{opener}: {detail}")

    return LaunchResult(False, None, "; ".join(failures) or f"no opener for {scheme}")


def find_snap_store_binary() -> str | None:
    """Locate App Center's executable, or return ``None`` when it is absent."""
    found = shutil.which(SNAP_STORE_NAME)
    if found:
        return found
    for path in SNAP_STORE_PATHS:
        if _is_executable(path):
            return path
    return shutil.which(SNAP_STORE_ALIAS)


def _open_in_browser(
    url: str, browser_opener: Callable[[str], object] | None
) -> LaunchResult:
    if browser_opener is None:
        return LaunchResult(False, None, f"no browser opener for {url}")
    try:
        browser_opener(url)
    except Exception as error:  # the worker must report, never crash
        return LaunchResult(False, "browser", f"{type(error).__name__}: {error}")
    return LaunchResult(True, "browser")


def _fallback_strategies(url: str) -> Iterator[tuple[str, list[str]]]:
    """Yield the native launchers, in preference order.

    gio consults the desktop MIME/scheme registry, unlike xdg-open which may
    silently fall back to a browser. Both only report that the request was
    spawned, so callers must confirm the handler first (see open_external).
    """
    yield ("gio open", ["gio", "open", url])
    yield ("xdg-open", ["xdg-open", url])


def snap_url_handler() -> str | None:
    """Return the desktop id registered as the default ``snap://`` handler.

    ``LC_ALL=C`` keeps gio's "Default application" label parseable. Any error,
    a non-zero exit or unparseable output yields ``None``.
    """
    try:
        completed = subprocess.run(
            ["gio", "mime", SNAP_HANDLER_MIME],
            capture_output=True,
            text=True,
            timeout=HANDLER_QUERY_TIMEOUT,
            env={**os.environ, "LC_ALL": "C"},
        )
    except OSError, subprocess.SubprocessError:
        return None
    if completed.returncode != 0:
        return None
    return _parse_default_handler(completed.stdout or "")


def _parse_default_handler(output: str) -> str | None:
    """Extract the desktop id from ``gio mime`` output."""
    for line in output.splitlines():
        label, separator, value = line.partition(":")
        if separator and "default application" in label.lower():
            return value.strip() or None
    return None


def _is_app_center_handler(desktop_id: str | None) -> bool:
    if not desktop_id:
        return False
    name = desktop_id.rsplit("/", 1)[-1].lower()
    return name.startswith(APP_CENTER_HANDLER_PREFIXES)


def _handler_rejection(desktop_id: str | None) -> str:
    if desktop_id is None:
        return "native fallbacks: skipped, no snap:// handler registered"
    return f"native fallbacks: skipped, snap:// handler is {desktop_id!r}"


def _run(argv: list[str], *, tolerate_running: bool) -> tuple[bool, str | None]:
    """Run *argv* and report ``(opened, failure_detail)``."""
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except (OSError, ValueError) as error:
        return False, f"could not run {argv[0]}: {error}"

    try:
        _, stderr = process.communicate(timeout=LAUNCH_TIMEOUT)
    except subprocess.TimeoutExpired:
        if tolerate_running:
            # Still running after the timeout means the launcher started and
            # stayed in the foreground; that is the desired outcome, so do not
            # kill it. Close the pipe to avoid leaking the descriptor.
            stream = getattr(process, "stderr", None)
            if stream is not None:
                stream.close()
            return True, None
        process.kill()
        process.communicate()
        return False, f"timed out after {LAUNCH_TIMEOUT:g}s"

    if process.returncode != 0:
        return False, _stderr_summary(stderr) or f"exit status {process.returncode}"
    if _stderr_indicates_failure(stderr):
        return False, _stderr_summary(stderr)
    return True, None


def _stderr_summary(stderr: str | None) -> str | None:
    text = " ".join((stderr or "").split())
    return text or None


def _stderr_indicates_failure(stderr: str | None) -> bool:
    text = (stderr or "").lower()
    return any(marker in text for marker in _FAILURE_MARKERS)


def _is_executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)
