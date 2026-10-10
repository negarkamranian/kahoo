"""Shopify product taxonomy; levels and IDs retain their upstream meaning."""

from pydantic import BaseModel, Field


class TaxonomyValue(BaseModel):
    id: str
    name: str
    handle: str


class AttributeAlias(BaseModel):
    name: str
    handle: str


class AttributeSummary(BaseModel):
    id: str
    name: str
    handle: str
    description: str


class AttributeReference(AttributeSummary):
    extended: bool


class TaxonomyAttribute(AttributeSummary):
    extended_attributes: list[AttributeAlias]
    values: list[TaxonomyValue]


class CategoryAttribute(AttributeReference):
    values: list[TaxonomyValue]


class ProductCategory(BaseModel):
    id: str
    code: str
    level: int = Field(ge=0)
    name: str
    full_name: str
    parent_id: str | None
    attributes: list[AttributeReference]


class ProductCategoryTree(ProductCategory):
    children: list["ProductCategoryTree"] = Field(default_factory=list)


class TaxonomyMetadata(BaseModel):
    version: str
    locale: str
    source_url: str
    download_url: str
    source_commit: str
    source_sha256: str
    categories: int
    attributes: int
    values: int


class ProductTaxonomy(BaseModel):
    metadata: TaxonomyMetadata
    categories: list[ProductCategory]
    attributes: list[TaxonomyAttribute]
