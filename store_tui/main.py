import argparse
import asyncio
import logging
import re
from pathlib import Path

from snap_python.client import SnapClient
from snap_python.schemas.store.categories import CategoryResponse
from snap_python.schemas.store.info import VALID_SNAP_INFO_FIELDS
from snap_python.schemas.store.search import SearchResponse
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import DataTable, Footer, Header, Input

from store_tui.elements.category_modal import CategoryModal
from store_tui.elements.error_modal import ErrorModal
from store_tui.elements.position_count import PositionCount
from store_tui.elements.search_modal import SnapSearchModal
from store_tui.elements.snap_modal import SnapModal
from store_tui.elements.snap_result_table import SnapResultTable
from store_tui.elements.utils import convert_snaps_to_search_response

logger = logging.getLogger(__name__)

snaps_api = SnapClient(
    store_base_url="https://api.snapcraft.io",
    version="v2",
    store_headers={"Snap-Device-Series": "16", "X-Ubuntu-Series": "16"},
    prompt_for_authentication=True,
)
TABLE_COLUMNS = ("Name", "Description")

parser = argparse.ArgumentParser(description="Snap Store TUI")
parser.add_argument("snap", help="Snap name to open on start", nargs="?")


class SnapStoreTUI(App):
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("c", "choose_category", "Category"),
        ("s", "search_snaps", "Search"),
        ("i", "list_installed_snaps", "Installed"),
    ]
    CSS_PATH = Path(__file__).parent / "styles" / "main.tcss"

    def __init__(self, api: SnapClient, preload_snap: str | None = None) -> None:
        super().__init__()
        self.current_category = "featured"
        self.all_categories: list[str] = []
        self.api = api
        self.preload_snap = preload_snap

        self.update_title()
        self.table_position_count = PositionCount(id="table-position-count")
        self.data_table = SnapResultTable(
            table_position_count=self.table_position_count, table_columns=TABLE_COLUMNS
        )
        self.header = Header()
        self.header.tall = False
        self.snapd_api_available = False

    def compose(self) -> ComposeResult:
        yield self.header
        yield self.data_table
        with Horizontal(id="footer-outer"):
            with Horizontal(id="footer-inner"):
                yield Footer(show_command_palette=False)
            yield self.table_position_count

    async def action_quit(self):
        self.exit()

    @work
    async def action_choose_category(self):
        self.current_category = await self.push_screen(
            CategoryModal(
                categories=self.all_categories,
                current_category=self.current_category,
            ),
            wait_for_dismiss=True,
        )
        top_snaps = self.api.store.get_top_snaps_from_category(self.current_category)
        await self.data_table.update_table(top_snaps=top_snaps)
        self.update_title()

    @work
    async def action_search_snaps(self):
        # open modal
        # get search query
        search_query: Input.Submitted = await self.push_screen(
            SnapSearchModal(), wait_for_dismiss=True
        )
        self.current_category = "Search"
        # send to update table to use "find" method
        top_snaps = self.api.store.find(
            query=search_query.value, fields=["title", "store-url", "summary"]
        )
        await self.data_table.update_table(top_snaps=top_snaps)
        self.update_title()

    @work
    async def action_list_installed_snaps(self):
        if not self.snapd_api_available:
            self.push_screen(
                ErrorModal(
                    ConnectionError(
                        "Snapd API not available - need snapd-control interface connected"
                    ),
                    error_title="Error - listing installed snaps",
                )
            )
            return

        try:
            installed_snaps = await self.api.snaps.list_installed_snaps()
            installed_snaps = convert_snaps_to_search_response(installed_snaps.result)
        except Exception as e:
            self.push_screen(
                ErrorModal(e, error_title="Error - listing installed snaps")
            )
            installed_snaps = SearchResponse(results=[])  # type: ignore

        if installed_snaps:
            await self.data_table.update_table(top_snaps=installed_snaps)

    def update_title(self):
        """Set title based on the current category"""
        self.title = f"store-tui - {self.current_category.capitalize()}"

    async def on_mount(self):
        self.data_table.loading = True
        self.call_after_refresh(self.init_main_screen)
        if self.preload_snap:
            self.call_after_refresh(self.load_snap_screen, snap_name=self.preload_snap)

    async def init_main_screen(self):
        try:
            categories_response = await self.api.store.get_categories()
            self.all_categories = [
                category.name or ""
                for category in (categories_response.categories or [])
            ]
            top_snaps = self.api.store.get_top_snaps_from_category(
                self.current_category
            )
        except Exception as e:
            logger.exception("Error getting categories or top snaps")
            categories_response = CategoryResponse(categories=[])
            self.all_categories = ["featured"]
            top_snaps = SearchResponse(results=[])  # type: ignore
            self.push_screen(
                ErrorModal(e, error_title="Error - getting categories or top snaps")
            )
        finally:
            self.data_table.loading = False
        await self.data_table.update_table(top_snaps=top_snaps)
        if self.data_table.row_count > 0:
            self.data_table.focus()

        # check snapd api access
        try:
            await self.api.ping()
            self.snapd_api_available = True
        except Exception:
            self.snapd_api_available = False

    async def load_snap_screen(self, snap_name: str):
        try:
            self.data_table.loading = True
            if self.snapd_api_available:
                snap_install_data = self.api.snaps.get_snap_info(snap_name)
            else:
                # empty await
                snap_install_data = asyncio.sleep(0)
            snap_info = self.api.store.retry_get_snap_info(
                snap_name=snap_name, fields=VALID_SNAP_INFO_FIELDS
            )
            snap_install_data, snap_info = await asyncio.gather(
                snap_install_data, snap_info
            )
        except Exception as e:
            self.push_screen(ErrorModal(e, error_title="Error - retrieving snap info"))
            snap_info = None
            snap_install_data = None
        finally:
            self.data_table.loading = False

        if snap_info is None:
            return
        snap_modal = SnapModal(
            snap_name=snap_name,
            api=self.api,
            snap_info=snap_info,
            snap_install_data=snap_install_data,
        )
        self.push_screen(snap_modal)

    @on(DataTable.RowSelected)
    async def on_data_table_row_selected(self, row_selected: DataTable.RowSelected):
        snap_row_key = row_selected.row_key.value
        assert snap_row_key is not None
        await self.load_snap_screen(snap_name=snap_row_key)


if __name__ == "__main__":
    args = parser.parse_args()

    if args.snap:
        # check if it starts with snap://
        # if it does, remove it using a regex

        args.snap = re.sub(r"^snap://", "", args.snap)

    SnapStoreTUI(api=snaps_api, preload_snap=args.snap).run()
