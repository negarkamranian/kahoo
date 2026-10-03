"""Normalized Instagram profiles, galleries, and media synchronization contracts."""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, computed_field

from backend.models.common import Count, InstagramHandle, NonEmptyText, TrimmedText

INSTAGRAM_MEDIA_SYNC_VERSION = 2
MAX_PROFILE_POSTS = 9
MINIMUM_POST_IMAGES = 3


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


class SyncBatch(BaseModel):
    profiles: list[SyncResult]
    attempted: int
    failed: int


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


class PostImage(BaseModel):
    post: InstagramPost
    image: InstagramImage
