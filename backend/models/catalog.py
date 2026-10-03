"""Reviewed merchant snapshots and catalog import results."""

from typing import Self

from pydantic import BaseModel, Field, model_validator

from backend.models.common import Count, InputModel, InstagramHandle


class CatalogImportResult(BaseModel):
    created: Count
    created_handles: list[str]
    enriched: Count


class CatalogMerchant(InputModel):
    handle: InstagramHandle
    name: str
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
