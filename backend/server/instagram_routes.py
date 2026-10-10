"""Real Instagram authorization endpoints, with safe callback redirects."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from backend.database import connect
from backend.instagram.oauth import InstagramConnectionError, login_configured
from backend.models.instagram.oauth import InstagramAuthorization, InstagramConnectionStatus
from backend.server.account_routes import (
    COOKIE_NAME,
    Session,
    ensure_session,
    require_account_mutation,
)
from backend.server.routes import RequestRoute
from backend.services.accounts import find_session, session_context
from backend.services.instagram_connections import (
    begin_authorization,
    complete_authorization,
    connection_status,
    consume_authorization,
)

router = APIRouter(prefix="/api/instagram", route_class=RequestRoute)
SAFE_CALLBACK_ERRORS = {
    "instagram_invalid_state",
    "instagram_not_configured",
    "instagram_permission_denied",
    "instagram_shop_excluded",
    "instagram_identity_conflict",
}


@router.post("/connect", dependencies=[Depends(require_account_mutation)])
def connect_instagram(request: Request, response: Response) -> InstagramAuthorization:
    if not login_configured():
        raise HTTPException(503, detail={"error": "instagram_not_configured"})
    context = ensure_session(request, response)
    try:
        url = begin_authorization(context)
    except InstagramConnectionError as error:
        status = 429 if str(error) == "instagram_rate_limited" else 503
        raise HTTPException(status, detail={"error": str(error)}) from error
    return InstagramAuthorization(authorization_url=url)


def callback_redirect(result):
    response = RedirectResponse(f"/?instagram={result}#connect", status_code=303)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def callback_session(request):
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise InstagramConnectionError("instagram_invalid_state")
    with connect() as db:
        row = find_session(db, token)
    if not row:
        raise InstagramConnectionError("instagram_invalid_state")
    return session_context(row)


@router.get("/callback")
def instagram_callback(request: Request):
    try:
        context = callback_session(request)
        consume_authorization(context, request.query_params.get("state", ""))
        if request.query_params.get("error"):
            return callback_redirect("instagram_permission_denied")
        code = request.query_params.get("code")
        if not code or len(code) > 4096:
            return callback_redirect("instagram_invalid_state")
        complete_authorization(context, code)
    except InstagramConnectionError as error:
        result = str(error) if str(error) in SAFE_CALLBACK_ERRORS else "instagram_connection_failed"
        return callback_redirect(result)
    except Exception:  # pylint: disable=broad-exception-caught
        # Provider, image or database failures must never leak tokens to the browser.
        return callback_redirect("instagram_connection_failed")
    return callback_redirect("connected")


@router.get("/connection")
def get_instagram_connection(session: Session) -> InstagramConnectionStatus:
    return connection_status(session)
