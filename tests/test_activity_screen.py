"""ActivityScreen: change loading, refresh, and abort behaviour."""

from __future__ import annotations

from unittest.mock import AsyncMock

from textual.app import App, ComposeResult
from textual.widgets import Static

from store_tui.screens.activity import ActivityScreen
from store_tui.screens.confirm import ConfirmScreen
from tests.support import FakeClient, change, changes_list


class HostApp(App[None]):
    def __init__(self) -> None:
        super().__init__()
        self.errors: list[tuple[object, str]] = []

    def compose(self) -> ComposeResult:
        yield Static("host")

    def show_error(self, error: object, title: str) -> None:
        self.errors.append((error, title))


class PlainHostApp(App[None]):
    def compose(self) -> ComposeResult:
        yield Static("host")


async def wait_until(pilot, predicate, attempts: int = 100) -> bool:
    for _ in range(attempts):
        if predicate():
            return True
        await pilot.pause()
    return predicate()


async def open_activity(pilot, client) -> ActivityScreen:
    screen = ActivityScreen(client=client)
    await pilot.app.push_screen(screen)
    await pilot.pause()
    return screen


async def test_loads_changes_and_formats_progress() -> None:
    client = FakeClient()
    client.changes.list_changes = AsyncMock(
        return_value=changes_list(
            [
                change(
                    "7",
                    summary="Install firefox",
                    kind="install-snap",
                    status="Doing",
                    done=1,
                    total=2,
                ),
                change(
                    "8",
                    summary="Remove snap",
                    kind="remove-snap",
                    status="Done",
                    ready=True,
                    done=0,
                    total=0,
                ),
            ]
        )
    )
    app = HostApp()
    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_activity(pilot, client)
        assert await wait_until(pilot, lambda: screen.table.row_count == 2)

        assert client.changes.list_changes.await_args.kwargs == {"select": "all"}
        assert screen.table.get_row("7") == [
            "Install firefox",
            "install-snap",
            "Doing",
            "1/2",
        ]
        assert screen.table.get_row("8") == [
            "Remove snap",
            "remove-snap",
            "Done",
            "-",
        ]
        assert screen.empty_label.display is False
        assert app.errors == []


async def test_empty_response_shows_empty_label() -> None:
    client = FakeClient()
    client.changes.list_changes = AsyncMock(return_value=changes_list([]))
    app = HostApp()
    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_activity(pilot, client)
        assert await wait_until(pilot, lambda: screen.table.row_count == 0)

        assert screen.empty_label.renderable == "No changes"
        assert screen.empty_label.display is True
        assert screen.changes == {}


async def test_refresh_reloads_changes() -> None:
    client = FakeClient()
    first = changes_list([change("1", summary="First")])
    second = changes_list([change("2", summary="Second")])
    client.changes.list_changes = AsyncMock(side_effect=[first, second])
    app = HostApp()

    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_activity(pilot, client)
        assert await wait_until(pilot, lambda: screen.table.row_count == 1)
        assert screen.table.get_row("1")[0] == "First"

        await pilot.press("r")
        assert await wait_until(
            pilot, lambda: client.changes.list_changes.await_count == 2
        )
        assert await wait_until(pilot, lambda: "2" in screen.changes)

        assert screen.table.row_count == 1
        assert screen.table.get_row("2")[0] == "Second"
        assert client.changes.list_changes.await_args.kwargs == {"select": "all"}


async def test_abort_selected_confirms_then_aborts_and_refreshes() -> None:
    client = FakeClient()
    running = change("3", summary="Install vim", ready=False)
    client.changes.list_changes = AsyncMock(
        side_effect=[
            changes_list([running]),
            changes_list(
                [change("3", summary="Install vim", ready=True, status="Done")]
            ),
        ]
    )
    client.changes.abort = AsyncMock(return_value=change("3", ready=True))
    app = HostApp()

    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_activity(pilot, client)
        assert await wait_until(pilot, lambda: screen.table.row_count == 1)

        screen.action_abort_selected()
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)

        await pilot.click("#confirm-confirm")
        assert await wait_until(pilot, lambda: client.changes.abort.await_count == 1)
        assert await wait_until(
            pilot, lambda: client.changes.list_changes.await_count == 2
        )

        assert await wait_until(pilot, lambda: screen.table.get_row("3")[2] == "Done")
        assert client.changes.abort.await_args.args == ("3",)
        assert "Aborting…" in str(screen.status_label.render())


async def test_ready_change_abort_only_warns() -> None:
    client = FakeClient()
    client.changes.list_changes = AsyncMock(
        return_value=changes_list([change("4", ready=True, status="Done")])
    )
    client.changes.abort = AsyncMock()
    app = HostApp()

    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_activity(pilot, client)
        assert await wait_until(pilot, lambda: screen.table.row_count == 1)

        screen.action_abort_selected()
        await pilot.pause()

        assert client.changes.abort.await_count == 0
        assert not isinstance(app.screen, ConfirmScreen)
        messages = [notification.message for notification in app._notifications]
        assert "Change already finished" in messages


async def test_abort_failure_is_reported_inline_not_as_error_screen() -> None:
    client = FakeClient()
    client.changes.list_changes = AsyncMock(
        return_value=changes_list([change("5", summary="Install vim", ready=False)])
    )
    client.changes.abort = AsyncMock(side_effect=RuntimeError("cannot abort change"))
    app = HostApp()

    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_activity(pilot, client)
        assert await wait_until(pilot, lambda: screen.table.row_count == 1)

        screen.action_abort_selected()
        await pilot.pause()
        await pilot.click("#confirm-confirm")

        assert await wait_until(
            pilot,
            lambda: "Abort failed" in str(screen.status_label.render()),
        )
        assert app.screen is screen
        assert app.errors == []
        messages = [notification.message for notification in app._notifications]
        assert any("Could not abort change 5" in message for message in messages)


async def test_list_failure_uses_show_error() -> None:
    client = FakeClient()
    failure = RuntimeError("snapd unavailable")
    client.changes.list_changes = AsyncMock(side_effect=failure)
    app = HostApp()

    async with app.run_test(size=(100, 40)) as pilot:
        await open_activity(pilot, client)
        assert await wait_until(pilot, lambda: bool(app.errors))

        error, title = app.errors[0]
        assert error is failure
        assert title == "Error - loading snapd activity"


async def test_list_failure_without_show_error_uses_status() -> None:
    client = FakeClient()
    client.changes.list_changes = AsyncMock(
        side_effect=RuntimeError("snapd unavailable")
    )
    app = PlainHostApp()

    async with app.run_test(size=(100, 40)) as pilot:
        screen = await open_activity(pilot, client)
        assert await wait_until(
            pilot, lambda: "snapd unavailable" in str(screen.status_label.render())
        )
        assert "Error - loading snapd activity" in str(screen.status_label.render())
        assert screen.table.row_count == 0
