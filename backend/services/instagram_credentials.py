"""Read and refresh encrypted credentials for an already authorized shop."""

from datetime import datetime, timedelta, timezone

from backend.config import settings
from backend.database import connect
from backend.instagram.oauth import (
    InstagramConnectionError,
    authorized_profile,
    refresh_token,
    token_cipher,
)


def current_access_token(db, row):
    now = datetime.now(timezone.utc)
    if row["expires_at"] <= now:
        raise InstagramConnectionError("instagram_token_expired")
    cipher = token_cipher()
    token = cipher.decrypt(row["token_ciphertext"].encode("ascii")).decode("utf-8")
    if row["expires_at"] < now + timedelta(days=7) and row["refreshed_at"] < now - timedelta(
        days=1
    ):
        refreshed = refresh_token(token)
        token = refreshed.access_token
        db.execute(
            """UPDATE instagram_connections SET token_ciphertext=%s,expires_at=%s,
                      refreshed_at=CURRENT_TIMESTAMP WHERE instagram_user_id=%s""",
            (
                cipher.encrypt(token.encode("utf-8")).decode("ascii"),
                now + timedelta(seconds=refreshed.expires_in),
                row["instagram_user_id"],
            ),
        )
    return token


def connected_profile(handle):
    if not settings.instagram_token_encryption_key:
        return None
    with connect() as db:
        row = db.execute(
            """SELECT c.* FROM instagram_connections c JOIN merchants m ON m.id=c.merchant_id
               WHERE m.handle=%s FOR UPDATE OF c""",
            (handle,),
        ).fetchone()
        if not row:
            return None
        token = current_access_token(db, row)
        instagram_user_id = row["instagram_user_id"]
    profile = authorized_profile(token)
    if profile.user_id != instagram_user_id:
        raise InstagramConnectionError("instagram_identity_mismatch")
    return profile.to_profile()
