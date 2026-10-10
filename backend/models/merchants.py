"""Merchant requests, public views, and import reports."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.models.categories import CategoryLink
from backend.models.common import Count, InputModel, InstagramHandle, NonEmptyText
from backend.models.media import PostCollection

MerchantPageSize = Annotated[int, Field(strict=True, ge=1, le=100)]


class MerchantRecommendation(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    identifier: InstagramHandle

    @field_validator("identifier", mode="before")
    @classmethod
    def normalize_handle(cls, value):
        if isinstance(value, str):
            return "@" + value.strip().lower().removeprefix("@")
        return value


class MerchantImport(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    identifier: InstagramHandle
    category_code: str | None = None
    city: NonEmptyText = "ایران"


class MerchantSummary(BaseModel):
    id: int
    name: str
    handle: str


class MerchantRemovalResult(BaseModel):
    removed: MerchantSummary


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
