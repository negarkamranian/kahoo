from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from backend.models.taxonomy import (
    AttributeSummary,
    CategoryAttribute,
    ProductCategory,
    ProductCategoryTree,
    TaxonomyAttribute,
    TaxonomyMetadata,
)
from backend.services.taxonomy import product_taxonomy

router = APIRouter(prefix="/api/taxonomy", tags=["Product taxonomy"])
PageLimit = Annotated[int, Query(ge=1, le=500)]
PageOffset = Annotated[int, Query(ge=0)]


@router.get("")
def metadata() -> TaxonomyMetadata:
    return product_taxonomy().taxonomy.metadata


@router.get("/tree")
def tree() -> list[ProductCategoryTree]:
    return product_taxonomy().tree()


@router.get("/categories")
def categories(
    q: str = "", parent: str | None = None, limit: PageLimit = 100, offset: PageOffset = 0
) -> list[ProductCategory]:
    items = product_taxonomy().taxonomy.categories
    if parent is not None:
        parent_id = category(parent).id if parent != "root" else None
        items = [item for item in items if item.parent_id == parent_id]
    if q:
        items = [item for item in items if q.casefold() in item.full_name.casefold()]
    return items[offset : offset + limit]


@router.get("/categories/{code}")
def category(code: str) -> ProductCategory:
    try:
        return product_taxonomy().category(code)
    except KeyError as error:
        raise HTTPException(404, detail="Unknown product category") from error


@router.get("/categories/{code}/attributes")
def category_attributes(code: str) -> list[CategoryAttribute]:
    try:
        return product_taxonomy().category_attributes(code)
    except KeyError as error:
        raise HTTPException(404, detail="Unknown product category") from error


@router.get("/attributes")
def attributes(
    q: str = "", limit: PageLimit = 100, offset: PageOffset = 0
) -> list[AttributeSummary]:
    items = product_taxonomy().taxonomy.attributes
    if q:
        items = [item for item in items if q.casefold() in f"{item.name} {item.handle}".casefold()]
    return items[offset : offset + limit]


@router.get("/attributes/{handle}")
def attribute(handle: str) -> TaxonomyAttribute:
    try:
        return product_taxonomy().attribute(handle)
    except KeyError as error:
        raise HTTPException(404, detail="Unknown product attribute") from error
