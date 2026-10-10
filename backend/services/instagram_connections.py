"""Session-bound authorization and atomic import of real Instagram shops."""

import re
import secrets
from datetime import datetime, timedelta, timezone

from backend.database import connect
from backend.instagram.oauth import (
    InstagramConnectionError,
    authorization_url,
    authorized_profile,
    exchange_code,
    login_configured,
    token_cipher,
)
from backend.instagram.urls import profile_url
from backend.models.instagram.oauth import InstagramConnection, InstagramConnectionStatus
from backend.models.media import MerchantMedia
from backend.models.merchants import MerchantImport
from backend.search.indexing import sync_search_index
from backend.services.accounts import token_digest
from backend.services.media import replace_profile_posts
from backend.services.merchants import create_imported_merchant, save_imported_avatar
from backend.services.profiles import save_profile_details

STATE_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


def begin_authorization(context):
    if not login_configured():
        raise InstagramConnectionError("instagram_not_configured")
    state = secrets.token_urlsafe(32)
    with connect() as db:
        db.execute("DELETE FROM instagram_oauth_states WHERE expires_at<CURRENT_TIMESTAMP")
        db.execute("SELECT id FROM app_users WHERE id=%s FOR UPDATE", (context.owner_id,))
        count = db.execute(
            """SELECT COUNT(*) AS count FROM instagram_oauth_states
               WHERE session_id=%s AND created_at>CURRENT_TIMESTAMP-INTERVAL '10 minutes'""",
            (context.session_id,),
        ).fetchone()["count"]
        if count >= 5:
            raise InstagramConnectionError("instagram_rate_limited")
        db.execute(
            "INSERT INTO instagram_oauth_states(state_hash,session_id) VALUES(%s,%s)",
            (token_digest(state), context.session_id),
        )
    return authorization_url(state)


def consume_authorization(context, state):
    if not STATE_PATTERN.fullmatch(state):
        raise InstagramConnectionError("instagram_invalid_state")
    with connect() as db:
        row = db.execute(
            """UPDATE instagram_oauth_states SET consumed_at=CURRENT_TIMESTAMP
               WHERE state_hash=%s AND session_id=%s AND consumed_at IS NULL
                 AND expires_at>CURRENT_TIMESTAMP RETURNING state_hash""",
            (token_digest(state), context.session_id),
        ).fetchone()
    if not row:
        raise InstagramConnectionError("instagram_invalid_state")


def find_authorized_merchant(db, identity):
    handle = identity.handle
    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (identity.user_id,))
    db.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (handle,))
    if db.execute("SELECT handle FROM merchant_exclusions WHERE handle=%s", (handle,)).fetchone():
        raise InstagramConnectionError("instagram_shop_excluded")
    rows = db.execute(
        """SELECT id,instagram_id,handle FROM merchants
           WHERE instagram_id=%s OR handle=%s FOR UPDATE""",
        (identity.user_id, handle),
    ).fetchall()
    if len(rows) > 1:
        raise InstagramConnectionError("instagram_identity_conflict")
    if rows:
        existing = rows[0]
        linked = db.execute(
            "SELECT instagram_user_id FROM instagram_connections WHERE merchant_id=%s",
            (existing["id"],),
        ).fetchone()
        if linked and linked["instagram_user_id"] != identity.user_id:
            raise InstagramConnectionError("instagram_identity_conflict")
        return existing["id"]
    db.execute(
        """INSERT INTO categories(code,level,label_fa,label_en,sort_order)
           VALUES('unclassified',1,'دسته‌بندی نشده','Unclassified',9999)
           ON CONFLICT(code) DO NOTHING"""
    )
    return create_imported_merchant(
        db, MerchantImport(identifier=handle), identity.to_profile(), "unclassified"
    )


def store_connection(db, context, identity, token, merchant_id):
    encrypted = token_cipher().encrypt(token.access_token.encode("utf-8")).decode("ascii")
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=token.expires_in)
    db.execute(
        """INSERT INTO instagram_connections(
             instagram_user_id,merchant_id,owner_id,username,token_ciphertext,expires_at)
           VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(instagram_user_id) DO UPDATE SET
             merchant_id=excluded.merchant_id,owner_id=excluded.owner_id,username=excluded.username,
             token_ciphertext=excluded.token_ciphertext,expires_at=excluded.expires_at,
             connected_at=CURRENT_TIMESTAMP,refreshed_at=CURRENT_TIMESTAMP""",
        (identity.user_id, merchant_id, context.owner_id, identity.username, encrypted, expires_at),
    )


def complete_authorization(context, code):
    if not login_configured():
        raise InstagramConnectionError("instagram_not_configured")
    token = exchange_code(code)
    identity = authorized_profile(token.access_token)
    profile = identity.to_profile()
    with connect() as db:
        active = db.execute(
            """SELECT user_id FROM user_sessions WHERE public_session_id=%s AND user_id=%s
               AND expires_at>CURRENT_TIMESTAMP FOR KEY SHARE""",
            (context.session_id, context.owner_id),
        ).fetchone()
        if not active:
            raise InstagramConnectionError("instagram_invalid_state")
        merchant_id = find_authorized_merchant(db, identity)
        db.execute(
            """UPDATE merchants SET instagram_id=%s,handle=%s,instagram_url=%s,
               updated_label='متصل به اینستاگرام' WHERE id=%s""",
            (identity.user_id, identity.handle, profile_url(identity.handle), merchant_id),
        )
        save_profile_details(db, MerchantMedia(id=merchant_id, handle=identity.handle), profile)
        save_imported_avatar(db, merchant_id, profile)
        replace_profile_posts(db, merchant_id, profile)
        if not profile.posts:
            db.execute("DELETE FROM merchant_posts WHERE merchant_id=%s", (merchant_id,))
        store_connection(db, context, identity, token, merchant_id)
        sync_search_index(db)
        db.execute(
            """INSERT INTO analytics_events(event_type,session_id,merchant_id)
               VALUES('oauth_completed',%s,%s)""",
            (context.session_id, merchant_id),
        )
    return merchant_id


def connection_status(context):
    with connect() as db:
        rows = db.execute(
            """SELECT c.merchant_id,m.name,m.handle,c.expires_at,
                      c.expires_at<=CURRENT_TIMESTAMP needs_reconnect
               FROM instagram_connections c JOIN merchants m ON m.id=c.merchant_id
               WHERE c.owner_id=%s ORDER BY c.connected_at DESC""",
            (context.owner_id,),
        )
        connections = [InstagramConnection.model_validate(row) for row in rows]
    return InstagramConnectionStatus(configured=login_configured(), connections=connections)
