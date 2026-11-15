"""Command line entry point for the Snap Store TUI."""

from __future__ import annotations

import argparse
import re

from store_tui.app import StoreApp
from store_tui.client import create_client

SNAP_SCHEME = re.compile(r"^snap://")


def normalize_snap_name(value: str | None) -> str | None:
    """Accept ``name`` or ``snap://name`` and return a bare snap name."""
    if value is None:
        return None
    name = SNAP_SCHEME.sub("", value.strip())
    return name or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="store-tui",
        description="Browse the Snap Store, inspect snaps, and install or remove them.",
    )
    parser.add_argument(
        "snap",
        nargs="?",
        help="Snap name to open on start (the snap:// prefix is accepted)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = StoreApp(
        client=create_client(),
        preload_snap=normalize_snap_name(args.snap),
    )
    app.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
