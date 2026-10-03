"""Instagram public embed payload models and domain conversion."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from backend.instagram_urls import post_url
from backend.models.common import NonEmptyText
from backend.models.instagram.common import Caption, Connection, CountConnection, SourceProfile
from backend.models.media import MAX_PROFILE_POSTS, InstagramImage, InstagramPost, InstagramProfile


class EmbedImage(BaseModel):
    id: NonEmptyText
    display_url: NonEmptyText

    def to_image(self, position: int) -> InstagramImage:
        return InstagramImage(
            instagram_media_id=self.id, image_url=self.display_url, media_position=position
        )


class EmbedPost(BaseModel, ABC):
    id: NonEmptyText
    shortcode: NonEmptyText
    edge_media_to_caption: Connection[Caption] = Field(default_factory=lambda: Connection(edges=[]))
    taken_at_timestamp: datetime | None = None

    @abstractmethod
    def images(self) -> list[InstagramImage]:
        raise NotImplementedError

    def to_post(self) -> InstagramPost:
        captions = self.edge_media_to_caption.edges  # pylint: disable=no-member
        return InstagramPost(
            instagram_media_id=self.id,
            caption=captions[0].node.text if captions else "",
            permalink=post_url(self.shortcode),
            published_at=self.taken_at_timestamp,
            media=self.images(),
        )


class EmbedSinglePost(EmbedPost):
    kind: Literal["GraphImage", "GraphVideo"] = Field(alias="__typename")
    display_url: NonEmptyText

    def images(self) -> list[InstagramImage]:
        return [InstagramImage(instagram_media_id=self.id, image_url=self.display_url)]


class EmbedCarouselPost(EmbedPost):
    kind: Literal["GraphSidecar"] = Field(alias="__typename")
    edge_sidecar_to_children: Connection[EmbedImage]

    def images(self) -> list[InstagramImage]:
        return [
            edge.node.to_image(position)
            for position, edge in enumerate(self.edge_sidecar_to_children.edges, 1)
        ]


class EmbedPostWrapper(BaseModel):
    shortcode_media: Annotated[EmbedSinglePost | EmbedCarouselPost, Field(discriminator="kind")]


class EmbedPosts(BaseModel):
    graphql_media: list[EmbedPostWrapper]

    def posts(self) -> list[InstagramPost]:
        return [item.shortcode_media.to_post() for item in self.graphql_media[:MAX_PROFILE_POSTS]]


class EmbedProfile(SourceProfile):
    username: NonEmptyText
    full_name: NonEmptyText
    profile_pic_url: str | None = None
    edge_followed_by: CountConnection | None = None
    edge_follow: CountConnection | None = None
    edge_owner_to_timeline_media: CountConnection | None = None
    is_verified: bool = False

    def to_profile(self, posts: list[InstagramPost]) -> InstagramProfile:
        return InstagramProfile(
            name=self.full_name,
            avatar_url=self.profile_pic_url,
            biography=self.biography,
            followers_count=self.edge_followed_by.count if self.edge_followed_by else None,
            following_count=self.edge_follow.count if self.edge_follow else None,
            media_count=self.edge_owner_to_timeline_media.count
            if self.edge_owner_to_timeline_media
            else None,
            instagram_verified=self.is_verified,
            posts=posts,
            source="instagram_public_embed",
        )


class EmbedContext(EmbedPosts):
    user: EmbedProfile
