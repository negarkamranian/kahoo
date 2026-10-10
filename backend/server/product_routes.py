"""Protected access to source evidence, extracted facts and review decisions."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from backend.models.products import (
    AdminProduct,
    ProductPage,
    ProductReview,
    ProductRun,
    ProductStatus,
    ReviewStatus,
)
from backend.server.routes import require_admin
from backend.services import products

router = APIRouter(prefix="/api/admin/products", dependencies=[Depends(require_admin)])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("")
def list_products(
    status: ProductStatus | None = None,
    review: ReviewStatus | None = None,
    q: str = "",
    limit: Limit = 50,
    offset: Offset = 0,
) -> ProductPage:
    return products.list_products(status, review, q, limit, offset)


@router.get("/{product_id}")
def get_product(product_id: int) -> AdminProduct:
    product = products.get_product(product_id)
    if not product:
        raise HTTPException(404, detail="محصول پیدا نشد")
    return product


@router.post("/enqueue")
def enqueue_existing():
    with products.connect() as db:
        return {"collections": products.enqueue_products(db)}


@router.get("/{product_id}/images/{position}")
def product_image(product_id: int, position: int):
    image = products.get_product_image(product_id, position)
    if not image:
        raise HTTPException(404, detail="تصویر پیدا نشد")
    return Response(
        bytes(image["image_blob"]),
        media_type=image["mime_type"],
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{product_id}/history")
def history(product_id: int) -> list[ProductRun]:
    get_product(product_id)
    return products.product_history(product_id)


@router.post("/{product_id}/review")
def submit_review(product_id: int, request: ProductReview) -> AdminProduct:
    get_product(product_id)
    if not products.review_product(product_id, request):
        raise HTTPException(409, detail="فقط نتیجه پردازش‌شده قابل ارزیابی است")
    return get_product(product_id)


@router.post("/{product_id}/retry")
def retry(product_id: int) -> AdminProduct:
    get_product(product_id)
    if not products.retry_product(product_id):
        raise HTTPException(409, detail="این محصول در حال پردازش است")
    return get_product(product_id)
