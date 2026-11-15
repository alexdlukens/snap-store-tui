# Snap Store TUI

[![Get it from the Snap Store](https://snapcraft.io/en/dark/install.svg)](https://snapcraft.io/store-tui)

A terminal user interface for browsing, searching, and installing snaps from the
Snap Store. Built with [Textual](https://github.com/textualize/textual/).

## Features

- Browse featured snaps and categories, with a live preview of the highlighted
  snap — icon, summary, and release metadata — beside the results, or below
  them when the terminal is narrow
- Search with store filters: confinement, category, publisher, architecture,
  channel, name prefix, and featured-only. Results update live as the form
  changes, the last query/filters are restored when you reopen the form, and
  plain queries support load-more
- Inspect snap details: icon, description, license, architectures, base, type,
  confinement, download size, and channels
- Install with separate track and risk pickers and a strict/classic/devmode/
  jailmode confinement choice
- Manage installed snaps in a dedicated screen: refresh, remove, hold/unhold
  refreshes, revert, disable/enable, and read service logs. Selecting a row opens
  the same store page used by search results, with installed state preloaded
- Watch snapd changes with live progress and cancel an operation
- Inspect recent and in-progress snapd changes in the Activity screen
- Open a snap's store page in the browser
- Jump from the details screen to App Center through its `snap://` deep link

Features that talk to snapd (installed snaps, install, management) degrade
gracefully when snapd is unavailable: the rest of the store view keeps working.

## Keyboard bindings

| Key       | Action                                                        |
| --------- | ------------------------------------------------------------- |
| `q`       | Quit from the store screen; also closes Snap/Install/Error    |
| `c`       | Open the category picker                                      |
| `s`       | Open the search form (query and filters)                      |
| `i`       | Open the installed-snaps management screen                    |
| `a`       | Open the snapd Activity screen                                |
| `m`       | Load more search results (plain queries)                      |
| `Enter`   | Open the selected snap's store page                           |
| `Escape`  | Close the active screen                                       |
| `↑` `↓`   | Move through lists and panes                                  |

On the Install screen, `i` installs, updates, or switches to the selected
channel, `r` reverts, `u` starts an uninstall, and Cancel aborts a running snapd
change. On the Installed screen, `Enter` or a row click opens the snap's store
page, `r` refreshes, `u` removes, `h` holds, `v` reverts, `d` disables/enables,
and `l` shows logs. Destructive actions ask for confirmation first.

The app-level bindings are inactive while a screen is open. Search and Category
close with `Escape` only (`q` is consumed as input in Search). Snap/Install/Error
accept `Escape` or `q`; Install and Installed refuse to close while a change is
running, but offer Cancel.

## Requirements

- Linux with snapd running and the snapd socket available at
  `/run/snapd.socket` (installed/install/uninstall features)
- Python 3.14 (from source)
- [uv](https://docs.astral.sh/uv/) for source installs and the `make` targets
- The published snap declares the `network`, `desktop`, `desktop-legacy`, and
  `snapd-control` plugs; `snapd-control` is what grants access to snapd.

The *App Center page* link on the details screen opens `snap://<name>` with
App Center: the `snap-store` binary (also looked up at `/snap/bin/snap-store`,
`/usr/bin/snap-store`, and `/usr/bin/app-center`), then `gio open`, then
`xdg-open`. The native fallbacks are used only when `gio mime
x-scheme-handler/snap` reports App Center as the registered handler, because
`gio`/`xdg-open` report success on spawn even when the link lands in another
app. It never hands the link to a web browser; if no launcher is available the
app shows a warning instead. Store pages (`https://`) still use the default
browser.

store-tui does not register the `snap://` scheme — App Center owns it. The CLI
still accepts a deep link as its argument, so `store-tui snap://vlc` opens the
details screen for `vlc` without changing any system-wide handler. Installs
that predate this change registered the scheme themselves; restore App Center
with `gio mime x-scheme-handler/snap snap-store_snap-store.desktop`.

## Install

From the Snap Store:

```bash
sudo snap install store-tui --edge
```

From source:

```bash
git clone https://github.com/alexdlukens/snap-store-tui
cd snap-store-tui
uv sync --locked
uv run --locked store-tui
```

## Development

All targets run from the repository root against the local `.venv`:

```bash
make install     # uv sync --locked
make run         # run the TUI
make dev         # run with the Textual dev console enabled
make test        # pytest
make lint        # ruff check
make fmt         # ruff format
make check       # lint + format check + tests
make build       # build sdist and wheel
make build-snap  # snapcraft pack
make lock        # refresh uv.lock
make clean       # remove build and cache artifacts
```

Snap builds use the `uv` plugin with `core24`; `astral-uv` is installed as a
build snap and dependencies come from `uv.lock`.

## Project layout

```text
store_tui/
  __main__.py    python -m store_tui entry point
  main.py        command line argument handling
  app.py         Textual application: store screen, bindings, workers
  client.py      snapd and store client setup
  launcher.py    opens external URLs (App Center deep links) without a browser
  snapd.py       typed installed-snap adapter over snap-python 0.2.0
  changes.py     shared change watching and progress formatting
  errors.py      snapd error-kind hints
  search.py      search filters, pagination helpers, row conversion
  screens/       category, search, snap details, install, installed,
                 activity, hold, logs, confirm, error
  widgets/       results table, channel tree, links, progress
  styles/app.tcss
  assets/        placeholder.png
snap/            snapcraft packaging and desktop integration
tests/           app/screen/foundation tests and fixtures (tests/data)
uv.lock          resolved dependency lockfile (commit this)
```

## License

MIT — see [LICENSE](LICENSE).
