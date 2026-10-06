"""Cookie-owned PostgreSQL sessions and a persistent, non-SMS demo login flow.

The demo accepts any five digits. A supplied phone must never discover another
owner or grant access to their data; verification only promotes the cookie's
existing guest row, and phone_verified remains false.
"""

import hashlib
import re
import secrets
from dataclasses import dataclass
from uuid import uuid4

from backend.database import connect
from backend.models.auth import (
    LoginChallenge,
    LoginRequest,
    LoginResult,
    LoginUser,
    LoginVerification,
    SessionContext,
)

SESSION_TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
LOGIN_REQUEST_LIMIT = 5


@dataclass(frozen=True)
class OpenedSession:
    context: SessionContext
    new_token: str | None = None


class LoginFlowError(ValueError):
    def __init__(self, code: str, status_code: int = 400):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def token_digest(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def session_context(row) -> SessionContext:
    user = None
    if row["logged_in_at"] is not None:
        user = LoginUser(
            id=row["user_id"],
            phone=row["phone"],
            display_name=row["display_name"],
            phone_verified=row["phone_verified"],
        )
    return SessionContext(
        owner_id=row["user_id"], session_id=str(row["public_session_id"]), user=user
    )


def find_session(db, token: str | None):
    if not token or not SESSION_TOKEN.fullmatch(token):
        return None
    return db.execute(
        """SELECT s.user_id,s.public_session_id,u.phone,u.display_name,
                  u.phone_verified,u.logged_in_at
           FROM user_sessions s JOIN app_users u ON u.id=s.user_id
           WHERE s.token_hash=%s AND s.expires_at>CURRENT_TIMESTAMP""",
        (token_digest(token),),
    ).fetchone()


def open_session(token: str | None) -> OpenedSession:
    with connect() as db:
        row = find_session(db, token)
        if row:
            return OpenedSession(session_context(row))
        new_token = secrets.token_urlsafe(32)
        public_id = str(uuid4())
        owner = db.execute("INSERT INTO app_users DEFAULT VALUES RETURNING id").fetchone()
        db.execute(
            "INSERT INTO user_sessions(token_hash,public_session_id,user_id) VALUES(%s,%s,%s)",
            (token_digest(new_token), public_id, owner["id"]),
        )
        context = SessionContext(owner_id=owner["id"], session_id=public_id)
        return OpenedSession(context, new_token)


def request_login(context: SessionContext, login: LoginRequest) -> LoginChallenge:
    with connect() as db:
        # Serialize per-owner limits and hold the current session through issue,
        # so concurrent logout cannot remove its challenge reference mid-write.
        owner = db.execute(
            """SELECT u.id FROM app_users u JOIN user_sessions s ON s.user_id=u.id
               WHERE u.id=%s AND s.public_session_id=%s AND s.expires_at>CURRENT_TIMESTAMP
               FOR UPDATE OF u FOR KEY SHARE OF s""",
            (context.owner_id, context.session_id),
        ).fetchone()
        if not owner:
            raise LoginFlowError("invalid_session")
        count = db.execute(
            """SELECT COUNT(*) AS count FROM login_challenges
               WHERE user_id=%s AND created_at>CURRENT_TIMESTAMP-INTERVAL '5 minutes'""",
            (context.owner_id,),
        ).fetchone()["count"]
        if count >= LOGIN_REQUEST_LIMIT:
            raise LoginFlowError("login_rate_limited", 429)
        challenge_id = str(uuid4())
        db.execute(
            """INSERT INTO login_challenges(challenge_id,user_id,session_id,phone)
               VALUES(%s,%s,%s,%s)""",
            (challenge_id, context.owner_id, context.session_id, login.phone),
        )
    return LoginChallenge(challenge_id=challenge_id, phone=login.phone)


def verify_login(context: SessionContext, login: LoginVerification) -> LoginResult:
    with connect() as db:
        challenge = db.execute(
            """UPDATE login_challenges SET consumed_at=CURRENT_TIMESTAMP
               WHERE challenge_id=%s AND user_id=%s AND session_id=%s AND phone=%s
                 AND consumed_at IS NULL AND expires_at>CURRENT_TIMESTAMP
               RETURNING user_id""",
            (login.challenge_id, context.owner_id, context.session_id, login.phone),
        ).fetchone()
        if not challenge:
            raise LoginFlowError("invalid_challenge")
        # This is a demo, not proof of phone ownership. Never select by phone.
        user = db.execute(
            """UPDATE app_users SET phone=%s,display_name=%s,phone_verified=false,
                      logged_in_at=CURRENT_TIMESTAMP WHERE id=%s
               RETURNING id,phone,display_name,phone_verified""",
            (login.phone, "حساب من", context.owner_id),
        ).fetchone()
    return LoginResult(user=LoginUser.model_validate(user))


def revoke_session(token: str | None) -> None:
    if not token or not SESSION_TOKEN.fullmatch(token):
        return
    with connect() as db:
        db.execute("DELETE FROM user_sessions WHERE token_hash=%s", (token_digest(token),))
