import requests

from snap_store_tui.schemas.snaps.categories import (
    VALID_CATEGORY_FIELDS,
    CategoryResponse,
    SingleCategoryResponse,
)


class SnapsAPI:
    def __init__(
        self, base_url: str, version: str, headers: dict[str, str] = None
    ) -> None:
        self.client = requests.Session()
        self.base_url = f"{base_url}/{version}"
        if headers is not None:
            self.client.headers.update(headers)

    def get_categories(
        self, type: str | None = None, fields: list[str] | None = None
    ) -> CategoryResponse:
        query = {}
        if fields is not None:
            if not all(field in VALID_CATEGORY_FIELDS for field in fields):
                raise ValueError(
                    f"Invalid fields. Allowed fields: {VALID_CATEGORY_FIELDS}"
                )
            query["fields"] = ",".join(fields)
        if type is not None:
            query["type"] = type
        route = "/snaps/categories"
        response = self.client.get(f"{self.base_url}{route}", params=query)
        response.raise_for_status()
        return CategoryResponse.model_validate_json(response.content)

    def get_category_by_name(self, name: str, fields: list[str] | None = None) -> SingleCategoryResponse:
        query = {}
        if fields is not None:
            if not all(field in VALID_CATEGORY_FIELDS for field in fields):
                raise ValueError(
                    f"Invalid fields. Allowed fields: {VALID_CATEGORY_FIELDS}"
                )
            query["fields"] = ",".join(fields)

        route = f"/snaps/category/{name}"
        response = self.client.get(f"{self.base_url}{route}", params=query)
        response.raise_for_status()
        return SingleCategoryResponse.model_validate_json(response.content)
