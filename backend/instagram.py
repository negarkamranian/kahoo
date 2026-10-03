import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def business_discovery_enabled():
    return all(os.environ.get(name) for name in ("META_IG_USER_ID", "META_ACCESS_TOKEN"))


def business_discovery_profile(handle):
    username = handle.lstrip("@").lower()
    version = os.environ.get("META_GRAPH_VERSION", "v26.0")
    ig_user_id = os.environ["META_IG_USER_ID"]
    fields = (
        f"business_discovery.username({username})"
        "{id,username,name,biography,website,profile_picture_url,"
        "followers_count,follows_count,media_count,"
        "media.limit(9){id,caption,media_type,media_product_type,"
        "media_url,thumbnail_url,permalink,timestamp,"
        "children.limit(20){id,media_type,media_url,thumbnail_url}}}"
    )
    query = urlencode(
        {
            "fields": fields,
            "access_token": os.environ["META_ACCESS_TOKEN"],
        }
    )
    url = f"https://graph.facebook.com/{version}/{ig_user_id}?{query}"
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=30) as response:
        payload = json.load(response)
    profile = payload["business_discovery"]
    posts = []
    for position, media in enumerate(profile.get("media", {}).get("data", []), 1):
        children = media.get("children", {}).get("data") or [media]
        images = []
        for child_position, child in enumerate(children, 1):
            image_url = child.get("media_url") or child.get("thumbnail_url")
            if not image_url:
                continue
            images.append(
                {
                    "instagram_media_id": child.get("id"),
                    "image_url": image_url,
                    "media_position": child_position,
                }
            )
        if not images:
            continue
        posts.append(
            {
                "instagram_media_id": media.get("id"),
                "collection_key": media.get("id"),
                "caption": media.get("caption") or "",
                "permalink": media.get("permalink") or f"https://www.instagram.com/{username}/",
                "published_at": media.get("timestamp"),
                "position": position,
                "media": images,
            }
        )
    return {
        "name": profile.get("name") or username,
        "avatar_url": profile.get("profile_picture_url"),
        "posts": posts,
        "biography": profile.get("biography") or "",
        "followers_count": profile.get("followers_count"),
        "following_count": profile.get("follows_count"),
        "media_count": profile.get("media_count"),
        "instagram_verified": False,
        "source": "meta_business_discovery",
        "media_grouping_version": 2,
    }
