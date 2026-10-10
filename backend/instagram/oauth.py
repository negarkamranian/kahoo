"""Instagram Login for professional accounts; never expose provider tokens to browsers.

Provider reference:
https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login/
"""

import json
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from cryptography.fernet import Fernet

from backend.config import settings
from backend.models.instagram.oauth import AuthorizedProfile, InstagramToken
from backend.models.media import MAX_PROFILE_POSTS

SCOPE = "instagram_business_basic"


class InstagramConnectionError(ValueError):
    """Safe, stable error codes instead of provider errors containing credentials."""


def token_cipher():
    try:
        return Fernet(settings.instagram_token_encryption_key.encode("ascii"))
    except (ValueError, UnicodeError) as error:
        raise InstagramConnectionError("instagram_not_configured") from error


def login_configured():
    try:
        uri = urlsplit(settings.instagram_redirect_uri)
    except ValueError:
        return False
    if not (settings.instagram_app_id and settings.instagram_app_secret):
        return False
    if uri.scheme != "https" or not uri.hostname or uri.query or uri.fragment or uri.username:
        return False
    if uri.path != "/api/instagram/callback":
        return False
    try:
        token_cipher()
    except InstagramConnectionError:
        return False
    return True


def authorization_url(state):
    return "https://www.instagram.com/oauth/authorize?" + urlencode(
        {
            "client_id": settings.instagram_app_id,
            "redirect_uri": settings.instagram_redirect_uri,
            "response_type": "code",
            "scope": SCOPE,
            "state": state,
            "enable_fb_login": "0",
            "force_authentication": "1",
        }
    )


def provider_request(url, *, params=None, form=None, token=None):
    headers = {"Accept": "application/json"}
    data = None
    if params:
        url += "?" + urlencode(params)
    if form:
        data = urlencode(form).encode("utf-8")
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, data=data, headers=headers), timeout=30) as response:
        result = json.load(response)
    if "error" in result:
        raise InstagramConnectionError("instagram_provider_failed")
    return result


def exchange_code(code):
    result = provider_request(
        "https://api.instagram.com/oauth/access_token",
        form={
            "client_id": settings.instagram_app_id,
            "client_secret": settings.instagram_app_secret,
            "redirect_uri": settings.instagram_redirect_uri,
            "grant_type": "authorization_code",
            "code": code,
        },
    )
    # Meta's Instagram Login response wraps the grant in a data array.
    grant = result["data"][0] if "data" in result else result
    if SCOPE not in grant.get("permissions", []):
        raise InstagramConnectionError("instagram_permission_denied")
    extended = provider_request(
        "https://graph.instagram.com/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": settings.instagram_app_secret,
            "access_token": grant["access_token"],
        },
    )
    return InstagramToken.model_validate(extended)


def refresh_token(token):
    result = provider_request(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token},
    )
    return InstagramToken.model_validate(result)


def authorized_profile(token):
    root = f"https://graph.instagram.com/{settings.meta_graph_version}"
    payload = provider_request(
        f"{root}/me",
        token=token,
        params={
            "fields": "user_id,username,name,account_type,biography,profile_picture_url,"
            "followers_count,follows_count,media_count",
        },
    )
    payload["media"] = provider_request(
        f"{root}/{payload['user_id']}/media",
        token=token,
        params={
            "limit": MAX_PROFILE_POSTS,
            "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,"
            "children.limit(20){id,media_type,media_url,thumbnail_url}",
        },
    )
    return AuthorizedProfile.model_validate(payload)
