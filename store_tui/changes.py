"""Shared snapd change watching and progress formatting."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from snap_python.schemas.changes import ChangesResponse
from snap_python.schemas.common import BaseErrorResult

CHANGE_TIMEOUT = 300.0


def change_result(change: ChangesResponse) -> Any | None:
    """Return the change result, or ``None`` for an error envelope."""
    result = change.result
    return None if isinstance(result, BaseErrorResult) else result


def progress_of(change: ChangesResponse) -> tuple[int, int | None, str]:
    """Return ``(done, total, message)`` for a progress widget.

    ``total`` is ``None`` when snapd has not reported a bounded total yet.
    """
    result = change_result(change)
    if result is None:
        return 0, None, "snapd reported an error"

    overall = result.overall_progress
    total = overall.total if overall.total and overall.total > 0 else None
    active = [task for task in result.tasks if task.status == "Doing"]
    message = active[0].summary if active else result.summary or "Working…"
    return overall.done, total, message


async def watch_change(
    client: Any,
    change_id: str,
    *,
    timeout: float | None = CHANGE_TIMEOUT,
    poll_interval: float = 0.5,
    on_change: Callable[[ChangesResponse], None] | None = None,
) -> ChangesResponse:
    """Watch ``change_id`` until ready.

    Uses the 0.2.0 ``changes.watch()`` stream, which raises
    :class:`snap_python.utils.SnapdAPIError` for failed changes and timeouts.
    """
    async for change in client.changes.watch(
        change_id, timeout=timeout, poll_interval=poll_interval
    ):
        if on_change is not None:
            on_change(change)
        if change.ready:
            return change
    raise RuntimeError("change stream ended before completion")
