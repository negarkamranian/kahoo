"""Validated model outputs and admin review contracts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

ShortText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Confidence = Annotated[float, Field(ge=0, le=1)]
ProductStatus = Literal["pending", "processing", "ready", "not_product", "failed"]
ReviewStatus = Literal["pending", "approved", "rejected"]


class ModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CategoryChoice(ModelOutput):
    category_code: ShortText | None
    is_product: bool
    confidence: Confidence
    evidence: ShortText


class AttributeValue(ModelOutput):
    handle: ShortText
    value: ShortText | None
    value_ids: list[ShortText] = Field(default_factory=list, max_length=30)
    confidence: Confidence
    evidence: ShortText | None
    source: Literal["caption", "image", "both", "unknown"]


class ProductExtraction(ModelOutput):
    title: ShortText
    description: str = Field(max_length=3000)
    attributes: list[AttributeValue] = Field(max_length=100)


class ExtractedAttribute(AttributeValue):
    name: str
    values: list[str] = Field(default_factory=list)


class ProductResult(BaseModel):
    title: str
    description: str = ""
    category_code: str | None
    category_name: str | None
    confidence: Confidence
    evidence: str
    attributes: list[ExtractedAttribute] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    images_used: int


class ProductImage(BaseModel):
    position: int
    media_url: str


class AdminProduct(BaseModel):
    id: int
    merchant_id: int
    merchant_name: str
    merchant_handle: str
    collection_key: str
    caption: str
    permalink: str
    status: ProductStatus
    result: ProductResult | None
    model: str | None
    taxonomy_version: str | None
    pipeline_version: str | None
    attempts: int
    error: str | None
    processed_at: datetime | None
    review_status: ReviewStatus
    review_note: str
    reviewed_at: datetime | None
    created_at: datetime
    images: list[ProductImage] = Field(default_factory=list)


class ProductPage(BaseModel):
    items: list[AdminProduct]
    total: int
    offset: int
    limit: int
    configured: bool


class ProductReview(ModelOutput):
    status: Literal["approved", "rejected"]
    note: str = Field(default="", max_length=3000)


class ProductRun(BaseModel):
    id: int
    source_hash: str
    model: str
    taxonomy_version: str
    pipeline_version: str
    status: str
    result: ProductResult | None
    error: str | None
    created_at: datetime
