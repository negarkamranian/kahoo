"""Canonical saved collections and bounded browser-migration requests."""

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from backend.models.common import InputModel

MerchantId = Annotated[int, Field(strict=True, gt=0)]
CollectionKey = Annotated[str, StringConstraints(min_length=1, max_length=512)]
Permalink = Annotated[str, StringConstraints(min_length=1, max_length=2048)]


class SavedMerchantReference(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    id: MerchantId


class SavedPostReference(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    merchant_id: MerchantId | None = None
    key: CollectionKey | None = None
    permalink: Permalink | None = None

    @model_validator(mode="after")
    def has_canonical_reference(self) -> Self:
        if not (self.merchant_id is not None and self.key is not None) and not self.permalink:
            raise ValueError("A merchant/key pair or canonical permalink is required")
        return self


class SavedImport(InputModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    merchants: list[SavedMerchantReference] = Field(default_factory=list, max_length=1000)
    posts: list[SavedPostReference] = Field(default_factory=list, max_length=1000)


class SavedMerchantView(BaseModel):
    key: str
    id: int
    name: str
    handle: str
    description: str
    avatar_url: str | None
    instagram_url: str
    city: str


class SavedPostView(BaseModel):
    key: str
    merchant_id: int
    merchant_name: str
    permalink: str
    media_url: str
    image_count: int


class SavedCollections(BaseModel):
    merchants: list[SavedMerchantView] = Field(default_factory=list)
    posts: list[SavedPostView] = Field(default_factory=list)


class SavedImportResult(SavedCollections):
    skipped_merchants: list[SavedMerchantReference] = Field(default_factory=list)
    skipped_posts: list[SavedPostReference] = Field(default_factory=list)
