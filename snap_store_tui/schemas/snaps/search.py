# generated by datamodel-codegen:
#   filename:  snaps_find_schema.json
#   timestamp: 2024-09-17T01:18:24+00:00


from typing import Any, Dict, List, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from snap_store_tui.schemas.snaps.categories import Category, Media

VALID_SEARCH_CATEGORY_FIELDS = [
    "base",
    "categories",
    "channel",
    "common-ids",
    "confinement",
    "contact",
    "description",
    "download",
    "license",
    "media",
    "prices",
    "private",
    "publisher",
    "revision",
    "store-url",
    "summary",
    "title",
    "type",
    "version",
    "website",
]


class ErrorListItem(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    code: str
    message: str


class Download(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    size: float


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    base: Optional[str] = None
    channel: Optional[str] = None
    common_ids: Optional[List[str]] = Field(None, alias="common-ids")
    confinement: Optional[str] = None
    download: Optional[Download] = None
    revision: Optional[float] = None
    type: Optional[str] = None
    version: Optional[str] = None


class Publisher(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    display_name: str = Field(
        ...,
        alias="display-name",
        description="Display name corresponding to the publisher.",
    )
    id: str = Field(..., description="The publisher id.")
    username: str = Field(..., description="Username belonging to the publisher.")
    validation: Optional[str] = Field(
        None, description="Indicates if the account has been validated."
    )


class Snap(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    categories: Optional[List[Category]] = None
    contact: Optional[str] = None
    description: Optional[str] = None
    gated_snap_ids: Optional[List[str]] = Field(None, alias="gated-snap-ids")
    license: Optional[str] = None
    links: Optional[Dict[str, Any]] = None
    media: Optional[List[Media]] = None
    name: Optional[str] = None
    prices: Optional[Dict[str, Any]] = None
    private: Optional[bool] = None
    publisher: Optional[Publisher] = Field(None, description="The publisher.")
    snap_id: Optional[str] = Field(None, alias="snap-id")
    store_url: Optional[str] = Field(None, alias="store-url")
    summary: Optional[str] = None
    title: Optional[str] = None
    trending: Optional[bool] = None
    unlisted: Optional[bool] = None
    website: Optional[str] = None


class SnapDetails(BaseModel):
    aliases: Optional[List[Dict]] = None
    anon_download_url: str
    apps: Optional[List[str]] = None
    architecture: List[str]
    base: Optional[str] = None
    binary_filesize: int
    channel: str
    common_ids: List[str]
    confinement: str
    contact: Optional[str] = None
    content: Optional[str] = None
    date_published: AwareDatetime
    deltas: Optional[List[str]] = None
    description: str
    developer_id: str
    developer_name: str
    developer_validation: str
    download_sha3_384: Optional[str] = None
    download_sha512: Optional[str] = None
    download_url: str
    epoch: str
    gated_snap_ids: Optional[List[str]] = None
    icon_url: str
    last_updated: AwareDatetime
    license: str
    links: Dict[str, Any]
    name: str
    origin: str
    package_name: str
    prices: Dict[str, Any]
    private: bool
    publisher: str
    raitings_average: float = 0.0
    release: List[str]
    revision: int
    screenshot_urls: List[str]
    snap_id: Optional[str] = None
    summary: Optional[str] = None
    support_url: Optional[str] = None
    title: Optional[str] = None
    version: Optional[str] = None
    website: Optional[str] = None


class SearchResult(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True, exclude_none=True)

    name: str
    revision: Optional[Revision] = None
    snap: Snap
    snap_id: str = Field(..., alias="snap-id")


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True, exclude_none=True)

    error_list: Optional[List[ErrorListItem]] = Field(None, alias="error-list")
    results: List[SearchResult]
