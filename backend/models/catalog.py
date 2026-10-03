"""Reviewed merchant snapshots and catalog import results."""

from pydantic import BaseModel, Field

from backend.models.common import Count, InputModel, InstagramHandle


class CatalogImportResult(BaseModel):
    created: Count
    created_handles: list[str]
    enriched: Count


class CatalogMerchantSnapshot(InputModel):
    """Supplied snapshot fields; omitted fields retain an earlier record's values."""

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


class CatalogMerchant(CatalogMerchantSnapshot):
    """Merged merchant record with a required name before import."""

    name: str

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
    merchants: list[CatalogMerchantSnapshot]

    def require_unique_handles(self) -> None:
        handles = [merchant.handle for merchant in self.merchants]
        if len(handles) != len(set(handles)):
            raise ValueError("duplicate merchant handle in catalog")
