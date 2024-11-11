# generated by datamodel-codegen:
#   filename:  snaps_info_schema.json
#   timestamp: 2024-10-17T01:47:02+00:00

from typing import List, Optional

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from store_tui.schemas.snaps.search import Snap

VALID_SNAP_INFO_FIELDS = [
    "architectures",
    "base",
    "categories",
    "channel-map",
    "common-ids",
    "confinement",
    "contact",
    "created-at",
    "description",
    "download",
    "epoch",
    "gated-snap-ids",
    "license",
    "links",
    "media",
    "name",
    "prices",
    "private",
    "publisher",
    "resources",
    "revision",
    "snap-id",
    "snap-yaml",
    "store-url",
    "summary",
    "title",
    "trending",
    "type",
    "unlisted",
    "version",
]


class Channel(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    architecture: str
    name: str
    released_at: Optional[AwareDatetime] = Field(None, alias="released-at")
    risk: str
    track: str


class Delta(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    format: str
    sha3_384: str = Field(..., alias="sha3-384")
    size: float
    source: float
    target: float
    url: str


class Download(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    deltas: List[Delta]
    sha3_384: str = Field(..., alias="sha3-384")
    size: float
    url: str


class Epoch(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    read: List[float]
    write: List[float]


class Download1(BaseModel):
    sha3_384: Optional[str] = Field(None, alias="sha3-384")
    size: Optional[int] = None
    url: Optional[str] = None


class Resource(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    architectures: Optional[List[str]] = None
    created_at: Optional[str] = Field(None, alias="created-at")
    description: Optional[str] = None
    download: Optional[Download1] = None
    name: Optional[str] = None
    revision: Optional[int] = None
    type: Optional[str] = None
    version: Optional[str] = None


class ChannelMapItem(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    architectures: Optional[List[str]] = None
    base: Optional[str] = None
    channel: Channel
    common_ids: Optional[List[str]] = Field(None, alias="common-ids")
    confinement: Optional[str] = None
    created_at: Optional[AwareDatetime] = Field(None, alias="created-at")
    download: Optional[Download] = None
    epoch: Optional[Epoch] = None
    resources: Optional[List[Resource]] = None
    revision: Optional[int] = None
    snap_yaml: Optional[str] = Field(None, alias="snap-yaml")
    type: Optional[str] = None
    version: Optional[str] = None


class ErrorListItem(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    code: str
    message: str


class InfoResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", exclude_unset=True)

    channel_map: List[ChannelMapItem] = Field(..., alias="channel-map")
    default_track: Optional[str] = Field(None, alias="default-track")
    error_list: Optional[List[ErrorListItem]] = Field(None, alias="error-list")
    name: str
    snap: Snap
    snap_id: str = Field(..., alias="snap-id")
