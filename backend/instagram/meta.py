"""Meta Business Discovery profile source."""

import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from backend.config import settings
from backend.models.instagram.meta import MetaProfile
from backend.models.media import MAX_PROFILE_POSTS, InstagramProfile


def business_discovery_enabled():
    return bool(settings.meta_ig_user_id and settings.meta_access_token)


def business_discovery_profile(handle: str) -> InstagramProfile:
    username = handle[1:]
    version = settings.meta_graph_version
    ig_user_id = settings.meta_ig_user_id
    fields = (
        f"business_discovery.username({username})"
        "{id,username,name,biography,website,profile_picture_url,"
        "followers_count,follows_count,media_count,"
        f"media.limit({MAX_PROFILE_POSTS}){{id,caption,media_type,media_product_type,"
        "media_url,thumbnail_url,permalink,timestamp,"
        "children.limit(20){id,media_type,media_url,thumbnail_url}}}"
    )
    query = urlencode({"fields": fields, "access_token": settings.meta_access_token})
    url = f"https://graph.facebook.com/{version}/{ig_user_id}?{query}"
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=30) as response:
        payload = json.load(response)
    return MetaProfile.model_validate(payload["business_discovery"]).to_profile()
