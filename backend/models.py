"""Data contracts shared by adapters and services. Parse untrusted data at the edges."""

from datetime import datetime
from enum import IntEnum
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    computed_field,
    field_validator,
    model_validator,
)

INSTAGRAM_MEDIA_SYNC_VERSION = 2
MAX_PROFILE_POSTS = 9
MINIMUM_POST_IMAGES = 3
Count = Annotated[int, Field(strict=True, ge=0)]
MerchantPageSize = Annotated[int, Field(strict=True, ge=1, le=100)]
SearchEntityType = Literal["merchant", "post"]
SuggestionType = Literal["merchant", "category", "query", "popular"]
NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TrimmedText = Annotated[str, StringConstraints(strip_whitespace=True)]
InstagramHandle = Annotated[str, StringConstraints(pattern=r"^@[a-z0-9._]{1,30}$")]


class InputModel(BaseModel):
    model_config = ConfigDict(strict=True)


class MerchantImport(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    identifier: InstagramHandle
    category_code: str | None = None
    city: NonEmptyText = "ایران"


class Enrichment(InputModel):
    description: str
    terms: list[str]
    model: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    confidence: float = Field(default=0.75, ge=0, le=1)


class AnalyticsEvent(InputModel):
    event_type: Literal[
        "search",
        "category_view",
        "merchant_click",
        "login_started",
        "login_completed",
        "oauth_started",
        "oauth_completed",
    ]
    session_id: str = Field(min_length=8, max_length=80)
    query: str | None = None
    category_code: str | None = None
    merchant_id: Count | None = None
    result_count: Count | None = None

    @field_validator("session_id")
    @classmethod
    def valid_session_id(cls, value: str) -> str:
        if not all(char.isascii() and (char.isalnum() or char in "_-") for char in value):
            raise ValueError("invalid session ID")
        return value


class LoginRequest(InputModel):
    phone: str | None = None


class LoginVerification(LoginRequest):
    code: str = Field(min_length=5, max_length=5)


class MetricsPeriod(IntEnum):
    WEEK = 7
    MONTH = 30
    QUARTER = 90


class MetricsKpis(BaseModel):
    searches: Count
    visitors: Count
    clicks: Count
    zero_rate: float
    search_to_click: float


class CatalogMetrics(BaseModel):
    merchants: Count
    used_categories: Count
    posts: Count
    avatars: Count
    descriptions: Count


class DailyMetrics(BaseModel):
    date: str
    searches: Count
    clicks: Count
    visitors: Count
    zero_results: Count


class QueryMetrics(BaseModel):
    query: str
    searches: Count


class TopQueryMetrics(QueryMetrics):
    avg_results: float | None
    zero_results: Count


class MerchantSummary(BaseModel):
    id: int
    name: str
    handle: str


class MerchantClickMetrics(MerchantSummary):
    clicks: Count


class CategoryViewMetrics(BaseModel):
    label: str
    views: Count


class FunnelMetrics(BaseModel):
    visitors: Count
    searched: Count
    clicked: Count
    oauth_started: Count
    oauth_completed: Count


class AdminMetrics(BaseModel):
    period_days: MetricsPeriod
    generated_at: datetime
    kpis: MetricsKpis
    catalog: CatalogMetrics
    daily: list[DailyMetrics]
    top_queries: list[TopQueryMetrics]
    missed_queries: list[QueryMetrics]
    top_merchants: list[MerchantClickMetrics]
    top_categories: list[CategoryViewMetrics]
    funnel: FunnelMetrics


class AdminMerchantQuery(InputModel):
    model_config = ConfigDict(strict=True, frozen=True)

    query: str = ""
    limit: MerchantPageSize = 50
    offset: Count = 0


class AdminMerchant(MerchantSummary):
    category_code: str
    city: str
    followers_count: int | None
    post_count: Count
    avatar_url: str | None


class AdminMerchantPage(BaseModel):
    items: list[AdminMerchant]
    total: Count
    limit: MerchantPageSize
    offset: Count


class CategoryNode(BaseModel):
    code: str
    parent_code: str | None
    level: Literal[1, 2, 3, 4]
    label_fa: str
    label_en: str | None
    icon: str | None
    count: Count
    children: list["CategoryNode"]


class SearchSuggestion(BaseModel):
    value: str
    label: str
    type: SuggestionType


class BenchmarkQuery(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    query: NonEmptyText
    relevance: dict[InstagramHandle, Annotated[int, Field(strict=True, ge=1, le=3)]] = Field(
        min_length=1
    )


class SearchBenchmark(InputModel):
    queries: list[BenchmarkQuery] = Field(min_length=1)


class MediaBackfillStatus(BaseModel):
    id: int
    handle: str
    missing_avatar: bool
    missing_posts: bool
    cached_images: Count
    media_sync_version: Count


class ImageCacheResult(BaseModel):
    attempted_images: Count
    cached_images: Count
    failed_images: Count


class CatalogImportResult(BaseModel):
    created: Count
    created_handles: list[str]
    enriched: Count


class InstagramImage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_url: NonEmptyText
    instagram_media_id: NonEmptyText
    media_position: Annotated[int, Field(strict=True, ge=1)] = 1


class InstagramPost(BaseModel):
    model_config = ConfigDict(extra="forbid")

    permalink: NonEmptyText
    media: list[InstagramImage] = Field(min_length=1)
    instagram_media_id: NonEmptyText
    caption: str = ""
    published_at: datetime | None = None

    @computed_field
    @property
    def collection_key(self) -> str:
        return self.instagram_media_id


class InstagramProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: NonEmptyText
    avatar_url: str | None = None
    posts: list[InstagramPost] = Field(default_factory=list, max_length=MAX_PROFILE_POSTS)
    biography: TrimmedText = ""
    followers_count: int | None = None
    following_count: int | None = None
    media_count: int | None = None
    instagram_verified: bool = False
    source: str = "instagram_public_embed"
    media_grouping_version: int = INSTAGRAM_MEDIA_SYNC_VERSION


class MerchantMedia(BaseModel):
    id: int
    handle: InstagramHandle
    name: str = ""
    description_source: str | None = None
    avatar_blob: bytes | None = None
    avatar_mime_type: str | None = None
    avatar_source_url: str | None = None
    cached_images: int = 0
    instagram_media_sync_version: int = 0

    @property
    def needs_avatar(self) -> bool:
        return (
            not self.avatar_blob
            or self.avatar_mime_type == "image/svg+xml"
            or not (self.avatar_source_url or "").startswith("http")
        )

    def needs_posts(self, minimum_images: int) -> bool:
        return (
            self.cached_images < minimum_images
            or self.instagram_media_sync_version < INSTAGRAM_MEDIA_SYNC_VERSION
        )

    def needs_media(self, minimum_images: int) -> bool:
        return self.needs_avatar or self.needs_posts(minimum_images)


class SyncResult(BaseModel):
    handle: str
    updated: bool
    error: str | None = None
    source: str | None = None
    mime_type: str | None = None
    posts_found: int = 0
    images_saved: int = 0
    avatar_saved: bool = False
    has_biography: bool = False
    needed_avatar: bool = False
    needed_posts: bool = False


class ImportResult(BaseModel):
    handle: str
    created: bool = False
    merchant_id: int | None = None
    name: str | None = None
    category_code: str | None = None
    followers_count: int | None = None
    avatar_saved: bool = False
    post_images_saved: int = 0
    error: str | None = None


class ImportBatch(BaseModel):
    results: list[ImportResult]
    failed: int


class SyncBatch(BaseModel):
    profiles: list[SyncResult]
    attempted: int
    failed: int


class CatalogMerchant(InputModel):
    handle: InstagramHandle
    name: str | None = None
    description: str | None = None
    category_code: str | None = None
    city: str | None = None
    source_url: str | None = None
    category_codes: list[str] = Field(default_factory=list)
    is_new: bool = False
    snapshot_at: str | None = None
    biography: str = ""
    biography_source: str | None = None
    description_source: str = "curated_public_directory"
    followers_count: Count | None = None
    media_count: Count | None = None
    metrics_source: str = "curated_public_directory"
    metrics_source_url: str | None = None
    quality_score: float | None = None
    review_count: Count = 0
    quality_source: str = "curated_public_directory"
    quality_source_url: str | None = None

    @model_validator(mode="after")
    def valid_catalog_entry(self) -> Self:
        if len(self.category_codes) != len(set(self.category_codes)):
            raise ValueError(f"duplicate category for {self.handle}")
        if self.is_new:
            self.require_details()
        return self

    def require_details(self) -> None:
        missing = [
            field
            for field in ("name", "description", "category_code", "city", "source_url")
            if getattr(self, field) is None
        ]
        if missing:
            raise ValueError(f"{self.handle}: new merchant needs {', '.join(missing)}")
        if not self.name:
            raise ValueError(f"{self.handle}: new merchant needs a name")


class MerchantCatalog(InputModel):
    snapshot_at: str = Field(min_length=1)
    merchants: list[CatalogMerchant]

    @model_validator(mode="after")
    def unique_handles(self) -> Self:
        handles = [merchant.handle for merchant in self.merchants]
        if len(handles) != len(set(handles)):
            raise ValueError("duplicate merchant handle in catalog")
        return self


class MediaAsset(BaseModel):
    media_url: str
    position: int


class PostCollection(BaseModel):
    post_id: int
    key: NonEmptyText
    permalink: str
    position: int
    media: list[MediaAsset] = Field(min_length=1)

    @computed_field
    @property
    def media_url(self) -> str:
        return self.media[0].media_url

    @computed_field
    @property
    def image_count(self) -> int:
        return len(self.media)


class CategoryLink(BaseModel):
    code: str
    label: str
    confidence: float | None = None
    source: str | None = None
    source_url: str | None = None


class Merchant(BaseModel):
    id: int
    name: str
    handle: str
    category_code: str
    city: str
    instagram_id: str | None = None
    description: str = ""
    description_source: str | None = None
    description_source_url: str | None = None
    description_generated_by: str | None = None
    description_updated_at: datetime | None = None
    source_url: str | None = None
    biography: str = ""
    biography_source: str | None = None
    biography_updated_at: datetime | None = None
    avatar_source_url: str | None = None
    avatar_updated_at: datetime | None = None
    instagram_url: str = ""
    updated_label: str = ""
    verified: int = 0
    verification_source: str | None = None
    verified_at: datetime | None = None
    followers_count: int | None = None
    following_count: int | None = None
    media_count: int | None = None
    former_username_count: int | None = None
    account_created_at: datetime | None = None
    metrics_source: str | None = None
    metrics_source_url: str | None = None
    metrics_updated_at: datetime | None = None
    created_at: datetime | None = None
    instagram_media_sync_version: int = 0
    instagram_media_synced_at: datetime | None = None
    directory_quality_score: float | None = None
    directory_review_count: int | None = None
    quality_source: str | None = None
    quality_source_url: str | None = None
    quality_updated_at: datetime | None = None
    avatar_url: str | None = None
    posts: list[PostCollection] = Field(default_factory=list)
    category_label: str | None = None
    category_path: list[CategoryLink] = Field(default_factory=list)
    categories: list[CategoryLink] = Field(default_factory=list)
    search_score: float = 0
    match_reason: str | None = None
    match_quality: Literal["exact", "near", "semantic"] | None = None
    match_coverage: float = 0
    matched_post_id: int | None = None


class LexicalMatch(BaseModel):
    score: float
    entity_type: SearchEntityType
    entity_id: int
    published_at: datetime | None = None
