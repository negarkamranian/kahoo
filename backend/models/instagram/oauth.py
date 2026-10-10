"""Private provider contracts and token-free browser responses."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.models.common import InstagramHandle, NonEmptyText
from backend.models.instagram.meta import MetaProfile


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
