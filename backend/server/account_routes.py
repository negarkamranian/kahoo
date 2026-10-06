"""Guest session and explicitly unverified demo-account endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from backend.models.auth import (
    LoginChallenge,
    LoginRequest,
    LoginResult,
    LoginVerification,
    LogoutResult,
    SessionContext,
    SessionResult,
)
from backend.server.routes import RequestRoute, require_private_mutation
from backend.services.accounts import (
    LoginFlowError,
    open_session,
    request_login,
    revoke_session,
    verify_login,
)

COOKIE_NAME = "kahoo_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365
router = APIRouter(route_class=RequestRoute)


def require_account_mutation(request: Request):
    require_private_mutation(request, "account_request_forbidden")


def ensure_session(request: Request, response: Response) -> SessionContext:
    session = open_session(request.cookies.get(COOKIE_NAME))
    response.headers["Cache-Control"] = "private, no-store"
    if session.new_token:
        response.set_cookie(
            COOKIE_NAME,
            session.new_token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            secure=request.url.scheme == "https",
            samesite="lax",
            path="/",
        )
    return session.context


Session = Annotated[SessionContext, Depends(ensure_session)]
MUTATION_DEPENDENCIES = [Depends(require_account_mutation)]


@router.get("/api/session")
def get_session(session: Session) -> SessionResult:
    return SessionResult(session_id=session.session_id, user=session.user)


@router.post("/api/login/request", dependencies=MUTATION_DEPENDENCIES)
def post_login_request(login: LoginRequest, request: Request, response: Response) -> LoginChallenge:
    context = ensure_session(request, response)
    try:
        return request_login(context, login)
    except LoginFlowError as error:
        raise HTTPException(error.status_code, detail={"error": error.code}) from error


@router.post("/api/login/verify", dependencies=MUTATION_DEPENDENCIES)
def post_login_verify(
    login: LoginVerification, request: Request, response: Response
) -> LoginResult:
    context = ensure_session(request, response)
    try:
        return verify_login(context, login)
    except LoginFlowError as error:
        raise HTTPException(error.status_code, detail={"error": error.code}) from error


@router.post("/api/logout", dependencies=MUTATION_DEPENDENCIES)
def post_logout(request: Request, response: Response) -> LogoutResult:
    revoke_session(request.cookies.get(COOKIE_NAME))
    response.headers["Cache-Control"] = "private, no-store"
    response.delete_cookie(
        COOKIE_NAME,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        path="/",
    )
    return LogoutResult()
