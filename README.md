# Snap Store TUI

[![Get it from the Snap Store](https://snapcraft.io/en/dark/install.svg)](https://snapcraft.io/store-tui)

A terminal user interface for browsing, searching, and installing snaps from the
Snap Store. Built with [Textual](https://github.com/textualize/textual/).

## Features

- Browse featured snaps and categories
- Search the Snap Store
- View installed snaps, including channel and confinement
- Inspect snap details: icon, description, license, architectures, channels
- Install and uninstall snaps with separate track and risk pickers and a
  strict/classic/devmode/jailmode confinement choice
- Open a snap's store page in the browser
- Jump from the details screen to App Center through its `snap://` deep link

Features that talk to snapd (installed snaps, install, uninstall) degrade
gracefully when snapd is unavailable: the rest of the store view keeps working.

## Keyboard bindings

| Key       | Action                                                        |
| --------- | ------------------------------------------------------------- |
| `q`       | Quit from the store screen; also closes Snap/Install/Error    |
| `c`       | Open the category picker                                      |
| `s`       | Open the search dialog                                        |
| `i`       | List installed snaps; on details: install / modify; on Install: install or switch |
| `u`       | On the install screen: uninstall (asks for confirmation)      |
| `Enter`   | Open the selected snap                                        |
| `Escape`  | Close the active screen                                       |
| `↑` `↓`   | Move through the snap list / track and risk panes             |

The app-level bindings (`q`/`c`/`s`/`i`) are inactive while a screen is open.
Search and Category close with `Escape` only (`q` is consumed as input in Search),
Snap/Install/Error accept `Escape` or `q`, and Install ignores `Escape` while an
install or removal is running. On the install screen, `i` installs or switches to
the selected channel and `u` starts an uninstall; uninstalling asks for confirmation
first, and cancelling or pressing `Escape` in that dialog removes nothing.

## Requirements

- Linux with snapd running and the snapd socket available at
  `/run/snapd.socket` (installed/install/uninstall features)
- Python 3.12 (from source)
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
poetry install
poetry run store-tui
```

## Development

All targets run from the repository root against the local `.venv`:

```bash
make install     # poetry install
make run         # run the TUI
make dev         # run with the Textual dev console enabled
make test        # pytest
make lint        # ruff check
make fmt         # ruff format
make check       # lint + format check + tests
make build-snap  # snapcraft pack
make clean       # remove build and cache artifacts
```

Snap builds use the `poetry` plugin with `core24`.

## Project layout

```text
store_tui/
  __main__.py    python -m store_tui entry point
  main.py        command line argument handling
  app.py         Textual application: store screen, bindings, workers
  client.py      snapd and store client setup
  launcher.py    opens external URLs (App Center deep links) without a browser
  snapd.py       snapd socket-backed installed/install/uninstall operations
  screens/       category, search, snap details, install, error screens
  widgets/       results table, channel tree, links, progress
  styles/app.tcss
  assets/        placeholder.png
snap/            snapcraft packaging and desktop integration
tests/           test_app.py and fixtures (tests/data)
```

## License

MIT — see [LICENSE](LICENSE).
