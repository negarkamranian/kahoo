"""Meta Business Discovery payload models and domain conversion."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from backend.models.common import NonEmptyText
from backend.models.instagram.common import DataList, SourceProfile
from backend.models.media import MAX_PROFILE_POSTS, InstagramImage, InstagramPost, InstagramProfile


class MetaImage(BaseModel):
    id: NonEmptyText
    media_type: Literal["IMAGE"]
    media_url: NonEmptyText

    def to_image(self, position: int) -> InstagramImage:
        return InstagramImage(
            instagram_media_id=self.id, image_url=self.media_url, media_position=position
        )


class MetaVideo(BaseModel):
    id: NonEmptyText
    media_type: Literal["VIDEO"]
    thumbnail_url: NonEmptyText

    def to_image(self, position: int) -> InstagramImage:
        return InstagramImage(
            instagram_media_id=self.id, image_url=self.thumbnail_url, media_position=position
        )


MetaMedia = Annotated[MetaImage | MetaVideo, Field(discriminator="media_type")]


class MetaPost(BaseModel, ABC):
    id: NonEmptyText
    permalink: NonEmptyText
    caption: str = ""
    timestamp: datetime | None = None

    @abstractmethod
    def images(self) -> list[InstagramImage]:
        raise NotImplementedError

    def to_post(self) -> InstagramPost:
        return InstagramPost(
            instagram_media_id=self.id,
            caption=self.caption,
            permalink=self.permalink,
            published_at=self.timestamp,
            media=self.images(),
        )


class MetaImagePost(MetaPost, MetaImage):
    def images(self) -> list[InstagramImage]:
        return [self.to_image(1)]


class MetaVideoPost(MetaPost, MetaVideo):
    def images(self) -> list[InstagramImage]:
        return [self.to_image(1)]


class MetaCarouselPost(MetaPost):
    media_type: Literal["CAROUSEL_ALBUM"]
    children: DataList[MetaMedia]

    def images(self) -> list[InstagramImage]:
        return [child.to_image(position) for position, child in enumerate(self.children.data, 1)]


MetaPostType = Annotated[
    MetaImagePost | MetaVideoPost | MetaCarouselPost, Field(discriminator="media_type")
]


class MetaProfile(SourceProfile):
    name: NonEmptyText
    profile_picture_url: str | None = None
    followers_count: int | None = None
    follows_count: int | None = None
    media_count: int | None = None
    media: DataList[MetaPostType] = Field(default_factory=lambda: DataList(data=[]))

    def to_profile(self) -> InstagramProfile:
        # Pylint sees the Pydantic default FieldInfo instead of the validated DataList.
        return InstagramProfile(
            name=self.name,
            avatar_url=self.profile_picture_url,
            biography=self.biography,
            followers_count=self.followers_count,
            following_count=self.follows_count,
            media_count=self.media_count,
            posts=[post.to_post() for post in self.media.data[:MAX_PROFILE_POSTS]],  # pylint: disable=no-member
            source="meta_business_discovery",
        )
