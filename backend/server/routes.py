import hmac
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import JsonValue
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.config import settings
from backend.database import connect
from backend.models.analytics import (
    AdminMetrics,
    AnalyticsEvent,
    AnalyticsRequest,
    AnalyticsResult,
    MetricsPeriod,
)
from backend.models.categories import CategoryNode
from backend.models.merchants import (
    AdminMerchantPage,
    AdminMerchantQuery,
    DemoImportResult,
    ImportResult,
    Merchant,
    MerchantImport,
    MerchantRecommendation,
    MerchantRemovalResult,
)
from backend.models.search import SearchSuggestion
from backend.search.service import merchants
from backend.search.suggestions import search_suggestions
from backend.services.analytics import admin_metrics, record_event
from backend.services.categories import category_tree
from backend.services.merchants import (
    add_or_refresh_merchant,
    admin_merchants,
    merchant_detail,
    recommend_merchant,
    remove_merchant,
)

MAX_REQUEST_BYTES = 1_048_576
ADMIN_DEFAULTS = AdminMerchantQuery()


class RequestRoute(APIRoute):
    """Reject invalid or oversized declared bodies before FastAPI reads them."""

    def get_route_handler(self):
        handler = super().get_route_handler()

        async def handle(request: Request):
            if request.method in {"POST", "PUT"}:
                validate_content_length(request)
            return await handler(request)

        return handle


router = APIRouter(route_class=RequestRoute)


def has_same_origin(request: Request) -> bool:
    origin = request.headers.get("Origin")
    if not origin:
        return True
    try:
        parts = urlsplit(origin)
    except ValueError:
        return False
    return (parts.scheme, parts.netloc) == (request.url.scheme, request.url.netloc)


def require_private_mutation(request: Request, code: str):
    if (
        request.headers.get("X-Kahoo-Saved") != "1"
        or request.headers.get("Sec-Fetch-Site") == "cross-site"
        or not has_same_origin(request)
    ):
        raise HTTPException(403, detail={"error": code})


def validate_content_length(request: Request):
    try:
        length = int(request.headers.get("Content-Length", "0"))
    except ValueError as error:
        raise HTTPException(400, detail={"error": "invalid_content_length"}) from error
    if length < 0:
        raise HTTPException(400, detail={"error": "invalid_content_length"})
    if length > MAX_REQUEST_BYTES:
        raise HTTPException(413, detail={"error": "request_too_large"})


VALIDATION_CODES = {
    "/api/login/request": "invalid_login",
    "/api/login/verify": "invalid_code",
    "/api/admin/merchants": "merchant_import_failed",
    "/api/merchants/recommend": "invalid_merchant_handle",
    "/api/admin/metrics": "invalid_period",
}


async def validation_error_response(request: Request, error: RequestValidationError):
    errors = error.errors()
    if any(item["loc"] == ("body",) or item["type"] == "json_invalid" for item in errors):
        return JSONResponse({"error": "invalid_json"}, status_code=400)
    if request.url.path == "/api/analytics/event":
        return JSONResponse({"saved": False}, status_code=400)
    if request.url.path.startswith("/api/saved"):
        return JSONResponse({"error": "invalid_saved_request"}, status_code=400)
    return route_validation_error(request, error)


def route_validation_error(request: Request, error: RequestValidationError):
    errors = error.errors()
    if any(item["loc"][0] == "path" for item in errors):
        if request.method == "DELETE":
            return JSONResponse({"error": "invalid_merchant_id"}, status_code=400)
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    if request.method == "GET" and request.url.path == "/api/admin/merchants":
        return JSONResponse({"error": "invalid_pagination"}, status_code=400)
    code = VALIDATION_CODES.get(request.url.path, "invalid_request")
    content = {"error": code}
    if code == "merchant_import_failed":
        content["message"] = str(error)
    return JSONResponse(content, status_code=400)


async def http_error_response(_request: Request, error: StarletteHTTPException):
    content = error.detail if isinstance(error.detail, dict) else {"detail": error.detail}
    return JSONResponse(content, status_code=error.status_code, headers=error.headers)


def admin_mutation_authorized(headers):
    configured = settings.admin_token
    if not configured:
        return True
    supplied = headers.get("X-Kahoo-Admin-Token", "")
    return bool(supplied) and hmac.compare_digest(configured, supplied)


def require_admin(request: Request):
    if not admin_mutation_authorized(request.headers):
        raise HTTPException(
            401, detail={"error": "unauthorized", "message": "کلید مدیریت نادرست است."}
        )


@router.get("/api/categories", response_model_exclude_unset=True)
def get_categories() -> list[CategoryNode]:
    return category_tree()


@router.get("/api/search/suggestions", response_model_exclude_unset=True)
def get_suggestions(q: str = "") -> list[SearchSuggestion]:
    return search_suggestions(q)


@router.get("/api/merchants", response_model_exclude_unset=True)
def get_merchants(
    q: str = "",
    category: Annotated[list[str] | None, Query(max_length=30)] = None,
    session_id: Annotated[str | None, Header(alias="X-Kahoo-Session")] = None,
) -> list[Merchant]:
    result = merchants(category, q)
    if session_id is not None and (q or category):
        event = AnalyticsEvent(
            event_type="search" if q else "category_view",
            session_id=session_id,
            query=q,
            category_code=category[0] if category else "",
            merchant_id=0,
            result_count=len(result),
        )
        record_event(event)
    return result


@router.get("/api/merchants/{merchant_id}", response_model_exclude_unset=True)
def get_merchant_detail(merchant_id: int) -> Merchant:
    result = merchant_detail(merchant_id)
    if result is None:
        raise HTTPException(404)
    return result


@router.get("/api/admin/metrics", response_model_exclude_unset=True)
def get_admin_metrics(
    days: Annotated[str, Query(pattern=r"^(7|30|90)$")] = str(MetricsPeriod.MONTH.value),
) -> AdminMetrics:
    return admin_metrics(MetricsPeriod(int(days)))


@router.get("/api/admin/merchants", response_model_exclude_unset=True)
def get_admin_merchants(
    q: str = "",
    limit: Annotated[int, Query(ge=1, le=100)] = ADMIN_DEFAULTS.limit,
    offset: Annotated[int, Query(ge=0)] = ADMIN_DEFAULTS.offset,
) -> AdminMerchantPage:
    return admin_merchants(AdminMerchantQuery(query=q, limit=limit, offset=offset))


@router.get("/api/media/{post_id}")
def get_media(post_id: int) -> Response:
    with connect() as db:
        media = db.execute(
            "SELECT image_blob,mime_type FROM merchant_posts WHERE id=%s", (post_id,)
        ).fetchone()
    if not media or media["image_blob"] is None:
        raise HTTPException(404)
    return Response(
        media["image_blob"],
        media_type=media["mime_type"] or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/api/avatars/{merchant_id}")
def get_avatar(merchant_id: int) -> Response:
    with connect() as db:
        avatar = db.execute(
            "SELECT avatar_blob,avatar_mime_type FROM merchants WHERE id=%s", (merchant_id,)
        ).fetchone()
    if not avatar or avatar["avatar_blob"] is None:
        raise HTTPException(404)
    return Response(
        avatar["avatar_blob"],
        media_type=avatar["avatar_mime_type"] or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.post("/api/analytics/event", status_code=201)
def post_analytics(
    payload: AnalyticsRequest,
    session_id: Annotated[str, Header(alias="X-Kahoo-Session", min_length=8, max_length=80)],
) -> AnalyticsResult:
    event = AnalyticsEvent(
        event_type=payload.event_type,
        session_id=session_id,
        query=payload.query,
        category_code=payload.category_code,
        merchant_id=payload.merchant_id,
        result_count=payload.result_count,
    )
    record_event(event)
    return AnalyticsResult(saved=True)


def import_demo_merchant() -> DemoImportResult:
    # A real OAuth callback would upsert the authenticated account. The demo must
    # never create a made-up public identity in the directory.
    return DemoImportResult(created=False, mode="oauth_demo")


@router.post("/api/merchants/import-demo", status_code=201)
def post_import_demo(_payload: Annotated[dict[str, JsonValue], Body()]) -> DemoImportResult:
    return import_demo_merchant()


@router.post(
    "/api/merchants/recommend",
    response_model_exclude_unset=True,
)
def post_merchant_recommendation(
    payload: MerchantRecommendation, request: Request, response: Response
) -> ImportResult:
    require_private_mutation(request, "invalid_merchant_recommendation")
    try:
        result = recommend_merchant(payload)
    except ValueError as error:
        raise HTTPException(
            400, detail={"error": "merchant_import_failed", "message": str(error)}
        ) from error
    except (OSError, RuntimeError) as error:
        raise HTTPException(
            502,
            detail={
                "error": "merchant_import_failed",
                "message": "دریافت فروشگاه از اینستاگرام ممکن نشد. دوباره تلاش کن.",
            },
        ) from error
    response.status_code = 201 if result.created else 200
    return result


@router.post(
    "/api/admin/merchants",
    dependencies=[Depends(require_admin)],
    response_model_exclude_unset=True,
)
def post_admin_merchant(request: MerchantImport, response: Response) -> ImportResult:
    result = add_or_refresh_merchant(request)
    response.status_code = 201 if result.created else 200
    return result


@router.delete("/api/admin/merchants/{merchant_id}", dependencies=[Depends(require_admin)])
def delete_admin_merchant(merchant_id: int) -> MerchantRemovalResult:
    removed = remove_merchant(merchant_id)
    if removed is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return MerchantRemovalResult(removed=removed)
