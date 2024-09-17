from unittest.mock import MagicMock

import pytest
from requests import Response
from requests.exceptions import HTTPError

from snap_store_tui.api.snaps import SnapsAPI
from snap_store_tui.schemas.snaps.categories import (
    CategoryResponse,
    SingleCategoryResponse,
)


@pytest.fixture(scope="function")
def setup_snaps_api():
    return SnapsAPI(base_url="http://localhost:8000", version="v1")


def test_get_categories_success(setup_snaps_api: SnapsAPI):
    setup_snaps_api.client.get = MagicMock()
    setup_snaps_api.client.get.return_value.status_code = 200
    setup_snaps_api.client.get.return_value.content = b'{"categories":[{"name":"art-and-design"},{"name":"books-and-reference"},{"name":"development"},{"name":"devices-and-iot"},{"name":"education"},{"name":"entertainment"},{"name":"featured"},{"name":"finance"},{"name":"games"},{"name":"health-and-fitness"},{"name":"music-and-audio"},{"name":"news-and-weather"},{"name":"personalisation"},{"name":"photo-and-video"},{"name":"productivity"},{"name":"science"},{"name":"security"},{"name":"server-and-cloud"},{"name":"social"},{"name":"utilities"}]}\n'
    response = setup_snaps_api.get_categories()
    assert isinstance(response, CategoryResponse)
    assert response.categories is not None
    assert len(response.categories) == 20


def test_get_categories_fail_bad_field(setup_snaps_api: SnapsAPI):
    setup_snaps_api.client.get = MagicMock()
    setup_snaps_api.client.get.return_value.status_code = 200
    setup_snaps_api.client.get.return_value.content = b'{"categories":[{"name":"art-and-design"},{"name":"books-and-reference"},{"name":"development"},{"name":"devices-and-iot"},{"name":"education"},{"name":"entertainment"},{"name":"featured"},{"name":"finance"},{"name":"games"},{"name":"health-and-fitness"},{"name":"music-and-audio"},{"name":"news-and-weather"},{"name":"personalisation"},{"name":"photo-and-video"},{"name":"productivity"},{"name":"science"},{"name":"security"},{"name":"server-and-cloud"},{"name":"social"},{"name":"utilities"}]}\n'
    try:
        setup_snaps_api.get_categories(fields=["bad-category"])
        pytest.fail("Expected ValueError")
    except ValueError:
        pass


def test_get_categories_fail_500(setup_snaps_api: SnapsAPI):
    setup_snaps_api.client.get = MagicMock()
    setup_snaps_api.client.get.return_value = Response()
    setup_snaps_api.client.get.return_value.status_code = 500

    try:
        setup_snaps_api.get_categories()
        pytest.fail("Expected HTTPError")
    except HTTPError:
        pass
