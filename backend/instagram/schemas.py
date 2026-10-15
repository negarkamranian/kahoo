"""Instagram provider payloads and authorization contracts."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.instagram.urls import post_url
from backend.models.common import InstagramHandle, NonEmptyText
from backend.models.media import MAX_PROFILE_POSTS, InstagramImage, InstagramPost, InstagramProfile

T = TypeVar("T")


class Edge(BaseModel, Generic[T]):
    node: T


class Connection(BaseModel, Generic[T]):
    edges: list[Edge[T]]


class DataList(BaseModel, Generic[T]):
    data: list[T]


class Caption(BaseModel):
    text: str


class SourceProfile(BaseModel):
    biography: str = ""


class CountConnection(BaseModel):
    count: int


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

    @field_validator("edge_sidecar_to_children", mode="before")
    @classmethod
    def skip_unavailable_images(cls, value):
        if not isinstance(value, dict) or not isinstance(value.get("edges"), list):
            return value
        edges = []
        for edge in value["edges"]:
            node = edge.get("node") if isinstance(edge, dict) else None
            if isinstance(node, dict) and "display_url" in node and not node["display_url"]:
                continue
            edges.append(edge)
        return {**value, "edges": edges}

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
    is_verified: bool | None = None
    external_url: str | None = None

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
            website_url=self.external_url,
            posts=posts,
            source="instagram_public_embed",
        )


class EmbedContext(EmbedPosts):
    user: EmbedProfile

    @model_validator(mode="before")
    @classmethod
    def accept_flat_profile(cls, value):
        if isinstance(value, dict) and "user" not in value and "username" in value:
            return {**value, "user": value}
        return value


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
    website: str | None = None
    media: DataList[MetaPostType] = Field(default_factory=lambda: DataList(data=[]))

    def to_profile(self) -> InstagramProfile:
        return InstagramProfile(
            name=self.name,
            avatar_url=self.profile_picture_url,
            biography=self.biography,
            followers_count=self.followers_count,
            following_count=self.follows_count,
            media_count=self.media_count,
            website_url=self.website,
            posts=[post.to_post() for post in self.media.data[:MAX_PROFILE_POSTS]],  # pylint: disable=no-member
            source="meta_business_discovery",
        )


class InstagramToken(BaseModel):
    access_token: NonEmptyText = Field(repr=False)
    expires_in: int = Field(gt=0)


class AuthorizedProfile(MetaProfile):
    user_id: NonEmptyText
    username: str = Field(pattern=r"^[A-Za-z0-9_.]{1,30}$")
    account_type: Literal["BUSINESS", "MEDIA_CREATOR"]
    name: str = ""

    @field_validator("user_id", mode="before")
    @classmethod
    def string_id(cls, value):
        return str(value) if isinstance(value, int) else value

    @model_validator(mode="after")
    def default_name(self):
        self.name = self.name or self.username
        return self

    @property
    def handle(self) -> InstagramHandle:
        return "@" + self.username.lower()

    def to_profile(self):
        profile = super().to_profile()
        profile.source = "instagram_oauth"
        return profile


class InstagramAuthorization(BaseModel):
    authorization_url: str


class InstagramConnection(BaseModel):
    merchant_id: int
    name: str
    handle: str
    expires_at: datetime
    needs_reconnect: bool


class InstagramConnectionStatus(BaseModel):
    configured: bool
    connections: list[InstagramConnection] = Field(default_factory=list)
