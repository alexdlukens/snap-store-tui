import pathlib
from unittest.mock import AsyncMock

import pytest

from store_tui.api.snaps import SnapsAPI
from store_tui.main import SnapStoreTUI
from store_tui.schemas.snaps.categories import (
    CategoryResponse,
)
from store_tui.schemas.snaps.search import SearchResponse

TESTS_DIR = pathlib.Path(__file__).parent
TESTS_DATA_DIR = TESTS_DIR / "data"


@pytest.fixture
def mocked_snaps_api():
    snaps_api = SnapsAPI(
        base_url="https://api.snapcraft.io",
        version="v2",
        headers={"Snap-Device-Series": "16", "X-Ubuntu-Series": "16"},
    )
    snaps_api.get_categories = AsyncMock(spec=SnapsAPI.get_categories)
    with open(TESTS_DATA_DIR / "categories_response.json") as f:
        snaps_api.get_categories.return_value = CategoryResponse.model_validate_json(
            f.read()
        )

    snaps_api.get_top_snaps_from_category = AsyncMock(
        spec=SnapsAPI.get_top_snaps_from_category
    )
    with open(TESTS_DATA_DIR / "featured_snaps.json") as f:
        snaps_api.get_top_snaps_from_category.return_value = (
            SearchResponse.model_validate_json(f.read())
        )

    return snaps_api


@pytest.mark.asyncio
async def test_load_ui_initial(mocked_snaps_api):
    app = SnapStoreTUI(api=mocked_snaps_api)

    async with app.run_test() as pilot:
        try:
            await pilot.pause()
        except Exception as e:
            pytest.fail(f"Unexpected exception: {e}")
