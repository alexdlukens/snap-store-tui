import pathlib
from unittest.mock import AsyncMock

from store_tui.api.snaps import SnapsAPI
from store_tui.main import SnapStoreTUI
from store_tui.schemas.snaps.categories import (
    CategoryResponse,
)
from store_tui.schemas.snaps.search import SearchResponse

TESTS_DIR = pathlib.Path(__file__).parent.parent / "tests"
TESTS_DATA_DIR = TESTS_DIR / "data"


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
    with open(TESTS_DATA_DIR / "featured_snaps_response.json") as f:
        snaps_api.get_top_snaps_from_category.return_value = (
            SearchResponse.model_validate_json(f.read())
        )

    return snaps_api


app = SnapStoreTUI(api=mocked_snaps_api())
app.run()