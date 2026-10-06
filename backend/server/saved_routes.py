"""Saved collections owned by the current persisted guest or account session."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response

from backend.models.auth import SessionContext
from backend.models.saved import CollectionKey, SavedCollections, SavedImport, SavedImportResult
from backend.server.account_routes import ensure_session
from backend.server.routes import RequestRoute, require_private_mutation
from backend.services.saved import (
    import_saved,
    save_merchant,
    save_post,
    saved_collections,
    saved_media,
    unsave_merchant,
    unsave_post,
)

MerchantPath = Annotated[int, Path(gt=0)]
router = APIRouter(route_class=RequestRoute)


def require_saved_mutation(request: Request):
    require_private_mutation(request, "saved_request_forbidden")


def saved_owner(
    response: Response, session: Annotated[SessionContext, Depends(ensure_session)]
) -> int:
    response.headers["Cache-Control"] = "private, no-store"
    return session.owner_id


Owner = Annotated[int, Depends(saved_owner)]
MUTATION_DEPENDENCIES = [Depends(require_saved_mutation)]


def require_collection(result: SavedCollections | None) -> SavedCollections:
    if result is None:
        raise HTTPException(404, detail={"error": "saved_reference_not_found"})
    return result


@router.get("/api/saved")
def get_saved(owner_id: Owner) -> SavedCollections:
    return saved_collections(owner_id)


@router.put("/api/saved/merchants/{merchant_id}", dependencies=MUTATION_DEPENDENCIES)
def put_saved_merchant(merchant_id: MerchantPath, owner_id: Owner) -> SavedCollections:
    return require_collection(save_merchant(owner_id, merchant_id))


@router.delete("/api/saved/merchants/{merchant_id}", dependencies=MUTATION_DEPENDENCIES)
def delete_saved_merchant(merchant_id: MerchantPath, owner_id: Owner) -> SavedCollections:
    return unsave_merchant(owner_id, merchant_id)


@router.put(
    "/api/saved/posts/{merchant_id}/{collection_key:path}", dependencies=MUTATION_DEPENDENCIES
)
def put_saved_post(
    merchant_id: MerchantPath, collection_key: CollectionKey, owner_id: Owner
) -> SavedCollections:
    return require_collection(save_post(owner_id, merchant_id, collection_key))


@router.delete(
    "/api/saved/posts/{merchant_id}/{collection_key:path}", dependencies=MUTATION_DEPENDENCIES
)
def delete_saved_post(
    merchant_id: MerchantPath, collection_key: CollectionKey, owner_id: Owner
) -> SavedCollections:
    return unsave_post(owner_id, merchant_id, collection_key)


@router.post("/api/saved/import", dependencies=MUTATION_DEPENDENCIES)
def post_saved_import(payload: SavedImport, owner_id: Owner) -> SavedImportResult:
    return import_saved(owner_id, payload)


@router.get("/api/saved/media/{merchant_id}/{collection_key:path}")
def get_saved_media(merchant_id: MerchantPath, collection_key: CollectionKey, owner_id: Owner):
    media = saved_media(owner_id, merchant_id, collection_key)
    if not media or media["image_blob"] is None:
        raise HTTPException(404, detail={"error": "saved_reference_not_found"})
    return Response(
        media["image_blob"],
        media_type=media["mime_type"] or "application/octet-stream",
        headers={"Cache-Control": "private, no-store"},
    )
