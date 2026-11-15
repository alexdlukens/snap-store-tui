"""Human-readable explanations for snapd failures."""

from __future__ import annotations

from typing import Any

KIND_HINTS: dict[str, str] = {
    "snap-change-conflict": (
        "Another snap operation is already in progress. Open Activity (a) to "
        "inspect or abort it."
    ),
    "login-required": (
        "This operation needs a Snap Store login. Run `snap login` and try again."
    ),
    "snap-not-found": "The store or snapd could not find that snap.",
    "auth-cancelled": "Authentication was cancelled.",
    "config-no-such-option": "That configuration option does not exist for this snap.",
    "snap-not-classic": "This snap is not installed with classic confinement.",
}

STATUS_HINTS: dict[int, str] = {
    401: "Permission denied. Is the snapd-control interface connected?",
    403: "Permission denied. Is the snapd-control interface connected?",
    404: "snapd could not find that object.",
    409: "snapd is busy with another change.",
}


def snapd_error_hint(error: Any) -> str | None:
    """Return a short actionable hint for a snapd exception, if one is known."""
    kind = getattr(error, "kind", None)
    if isinstance(kind, str) and kind in KIND_HINTS:
        return KIND_HINTS[kind]

    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and status in STATUS_HINTS:
        return STATUS_HINTS[status]

    status = getattr(error, "status_code", None)
    if isinstance(status, int) and status in STATUS_HINTS:
        return STATUS_HINTS[status]
    return None


def error_text_with_hint(error: Any) -> str:
    """Return a one-line description prefixed with the known hint."""
    hint = snapd_error_hint(error)
    try:
        text = str(error)
    except Exception:
        text = f"<{type(error).__name__} with unprintable message>"
    if hint and hint not in text:
        return f"{hint}\n\n{text}"
    return text
