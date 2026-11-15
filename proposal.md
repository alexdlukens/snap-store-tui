# store-tui × snap-python 0.2.0

0.2.0 turns `store_tui/snapd.py` from a defensive workaround into a dead end:
the package now accepts arbitrary base strings (including `core26`), parses
snapd error envelopes into `SnapdAPIError.kind`, and exposes typed installed
snaps, changes, holds, revisions, logs, and search filters.

This document records the agreed prioritisation and the implementation split.
It is intentionally concrete: every item names the 0.2.0 surface and the files
it touches.

## Current problems

- `snapd.py` exists because 0.1.7 rejected `core26` bases. 0.2.0 fixed that, so
  the module is now pure duplication of `SnapClient.snaps`.
- An installed snap on its current channel has no action: `InstallScreen`
  disables the button when `same_channel_installed`, so there is no refresh.
- `InstallScreen` forces `channel="stable"` when nothing is selected.
- Installs block a modal for `CHANGE_TIMEOUT = 300` seconds with no cancel.
- Search is query-only, first page only, and requests only
  `title/store-url/summary`.
- There is no installed management surface: the main table throws away
  version, channel, revision, hold, and refresh state.
- Errors are raw tracebacks even when snapd supplies an actionable `kind`.

## Prioritisation

| # | Pri | Improvement | 0.2.0 surface | Payoff | Effort |
|---|---|---|---|---|---|
| 1 | **P0** | Type the snapd layer | `snaps.list_installed_snaps()`, `get_installed_snap()`, `is_snap_installed()` | Delete the envelope parser; expose hold/refresh/broken/tracks/components | 1–1.5d |
| 2 | **P0** | Real update / switch / revert | `refresh_snap()`, `switch_channel()`, `revert_snap()`, `install_snap(revision=)` | Installed snaps can finally be updated and rolled back | 0.5–1d |
| 3 | **P0** | Cancellable operations | `changes.watch()`, `changes.abort()`, `SnapdAPIError.kind` | Stop blocking a modal for five minutes with no exit | 0.5d |
| 4 | **P1** | Installed management screen | typed `InstalledSnap` fields, remove/hold/disable/revert/logs, `list_installed_snaps(select="all")` | Installed view becomes a management surface | 2–3d |
| 5 | **P1** | Search filters + load-more | `find(confinement=, category=, publisher=, architecture=, channel=, name_startswith=)`; `get_snap_search_paginated()` | Search can actually use the store filters 0.2.0 fixed | 1.5–2d |
| 6 | **P1** | Activity/changes screen | `changes.list_changes(select=)`, `watch()`, `abort()` | Surface auto-refreshes and external snapd changes | 1–1.5d |
| 7 | **P1** | Error-kind mapping | `SnapdAPIError.kind` / `.value` | Actionable messages instead of a traceback | 0.5d |
| 8 | **P1** | Details accuracy/enrichment | `InfoResponse.supported_architectures`, `ChannelMapItem.supported_architectures` | Correct arch list; base/type/confinement/size | 0.5d |
| 9 | P2 | Update-available badge | `store.snap_refresh()` | Batch compare installed revisions with the store | 1d |
| 10 | P2 | Permissions/interfaces | `interfaces.connections(snap=)`, `connect/disconnect` | Show confinement exposure | 1.5–2d |
| 11 | P3 | Batch operations | `refresh_snaps`, `remove_snaps`, `hold_snaps` | Multi-select actions | 1.5d |
| 12 | P3 | Services / system / components | `start_apps`, `stop_apps`, `restart_apps`, `get_system_info`, component fields | Later polish | 2–3d |

## P0 scope

### 1. Typed snapd layer

Rewrite `store_tui/snapd.py` as a typed adapter over `SnapClient.snaps`:

- `get_installed_state(client, name)` → `InstalledState` via
  `get_installed_snap()` (404 is `None`, other errors are surfaced).
- `list_installed(client, select=None)` → `InstalledSnapRow` via
  `list_installed_snaps()`.
- `list_revisions(client, name)` → all revisions via `select="all"`.
- Map `hold`, `gating_hold`, `refresh_inhibit`, `refresh_failures`, `broken`,
  `trymode`, `devmode`, `status`, `cohort_key`, `grade`, `tracks`,
  `components`, `installed_size`, and `install_date`.

No raw `client.request()` envelope parsing remains.

### 2. Update / switch / revert

`InstallScreen` keeps one primary button but changes its operation:

| State | Label | Call |
|---|---|---|
| Not installed | `Install <channel>` | `install_snap(channel=<channel>)` |
| Installed, same channel | `Update from <channel>` | `refresh_snap(channel=None)` |
| Installed, other channel | `Switch to <channel>` | `switch_channel(channel=<channel>)` |
| Installed, revert action | `Revert` | `revert_snap()` after confirmation |

Remove the unconditional `channel or "stable"` fallback. Keep purge/terminate
explicit in the uninstall confirmation.

### 3. Cancellable changes

Replace the hand-rolled `get_changes_by_id_generator()` loop with
`changes.watch(change_id, timeout=...)`. Store the change id, expose a
`Cancel` button while running, call `changes.abort(change_id)`, and map
`SnapdAPIError` through the shared error helper. A user-requested abort is not
reported as a failure.

## P1 scope

### 4. Installed management screen

New `screens/installed.py`:

- Table: name, version, tracking channel, revision, status.
- Details pane: size, install date, hold, refresh inhibit, broken, tracks.
- Actions: refresh, remove, hold/unhold, revert, disable/enable, logs, details.
- Watched changes with the same progress/cancel treatment as install.
- Empty state and snapd-unavailable error.

`i` opens this screen instead of repopulating the main table.

### 5. Search filters and pagination

New `store_tui/search.py`:

- `SearchFilters` with confinement, category, publisher, architecture, channel,
  name prefix, and featured.
- `find_kwargs()` that omits unset filters.
- Row conversion for `SearchResponse` and `PaginatedSnapSearchResponse`.

`SearchScreen` becomes a small form. It emits debounced preview requests while
the user types or changes a filter, so the main results table updates behind
the modal. The app keeps the last `SearchRequest` in memory for the session and
passes it back as the form's initial values. The app uses:
- `find()` when any advanced filter is set (no pagination).
- `get_snap_search_paginated()` for plain queries, with `m` to load the next
  page and append unique rows.

`ResultsTable` gains a `Version` column, `append_rows()`, and configurable
columns.

### 6. Activity screen

New `screens/activity.py`:

- `changes.list_changes(select="all")`.
- Columns: summary, kind, status, progress.
- `r` refresh, `a` abort selected (confirmation for in-progress changes).
- `SnapdAPIError.kind` is shown inline.

`a` opens it from the store screen.

### 7. Error kind mapping

New `store_tui/errors.py` maps `SnapdAPIError.kind` and HTTP status to a short
hint, prepended to the existing traceback. Known examples:
`snap-change-conflict`, `login-required`, `snap-not-found`, `auth-cancelled`.

### 8. Details accuracy

- Use `InfoResponse.supported_architectures` instead of re-deriving from
  `channel.architecture`.
- Add base, type, confinement, and download size to the details card.
- Extend the installed label with channel and hold/broken markers.

## Verification

- Update the fake `SnapClient` to the 0.2.0 surface.
- Keep the existing install/mode/layout coverage; update assertions for the
  new button semantics and cancellable changes.
- Add focused tests for typed installed fields, 404 vs error, search filter
  kwargs, pagination rows, installed actions, activity abort, error hints, and
  details architecture union.
- `make check` (ruff + format check + pytest) must pass.

## Implementation status (0.3.0 work)

P0 and P1 are implemented on top of snap-python 0.2.0:

- Typed snapd adapter (`snapd.py`), shared `changes.py`, and `errors.py`.
- Install screen now distinguishes install / update / switch / revert and
  exposes Cancel through `changes.abort`. Revert is keyboard-reachable with
  `r`.
- Dedicated installed screen with refresh, remove, hold/unhold, revert,
  disable/enable, logs, and cancellation.
- Search form with filters and paginated load-more. Pagination computes
  `total > page * SEARCH_PAGE_SIZE` because the library's `has_more`
  convenience property assumes zero-based pages while this endpoint is
  one-based.
- Activity screen with change progress and abort.
- `SnapdAPIError.kind` hints are prepended to the error screen and used by the
  activity and installed screens.
- Details use `InfoResponse.supported_architectures` and render base, type,
  confinement, and download size.

Verification: `make check` is green: 150 tests pass, `ruff check .` reports
no issues, and `ruff format --check .` is clean. The suite covers the typed adapter, install action dispatch, cancel
and revert, installed management actions, search filters/pagination, activity
abort, error hints, and details metadata.
