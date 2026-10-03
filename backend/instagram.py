import json
import os
import re
from datetime import datetime
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

INSTAGRAM_MEDIA_SYNC_VERSION = 2


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
        "media_grouping_version": INSTAGRAM_MEDIA_SYNC_VERSION,
    }


def normalize_identifier(identifier):
    value = str(identifier or "").strip().lower()
    if "://" in value:
        parsed = urlparse(value)
        if parsed.netloc not in {"instagram.com", "www.instagram.com"}:
            raise ValueError("the URL must be an instagram.com profile URL")
        value = parsed.path.strip("/").split("/", 1)[0]
    value = value.lstrip("@").strip("/")
    if not re.fullmatch(r"[a-z0-9._]{1,30}", value):
        raise ValueError("use an Instagram username, @username, or profile URL")
    return f"@{value}"


def instagram_shortcode(permalink):
    match = re.search(r"/(?:p|reel)/([^/?#]+)", permalink or "")
    return match.group(1) if match else ""


def extract_embed_posts(payload):
    """Read top-level posts and carousel children from Instagram's ServerJS data."""
    graphql_media = []

    def walk(value):
        nonlocal graphql_media
        if graphql_media:
            return
        if isinstance(value, dict):
            media = value.get("graphql_media")
            if isinstance(media, list):
                graphql_media = media
                return
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str) and "graphql_media" in value:
            try:
                walk(json.loads(value))
            except (json.JSONDecodeError, TypeError):
                pass

    decoder = json.JSONDecoder()
    for script in re.findall(r"<script[^>]*>(.*?)</script>", payload, re.DOTALL):
        if "graphql_media" not in script:
            continue
        for match in re.finditer(r"\b\w+\.handle\(", script):
            try:
                server_data, _ = decoder.raw_decode(script[match.end() :])
            except json.JSONDecodeError:
                continue
            walk(server_data)
            if graphql_media:
                break
        if graphql_media:
            break

    posts = []
    for wrapper in graphql_media[:9]:
        media = wrapper.get("shortcode_media") or wrapper
        shortcode = media.get("shortcode")
        if not shortcode:
            continue
        child_edges = media.get("edge_sidecar_to_children", {}).get("edges") or []
        children = [edge.get("node", {}) for edge in child_edges] or [media]
        images = []
        for media_position, child in enumerate(children, 1):
            image_url = child.get("display_url") or child.get("thumbnail_src")
            if not image_url:
                continue
            images.append(
                {
                    "instagram_media_id": child.get("id"),
                    "image_url": image_url,
                    "media_position": media_position,
                }
            )
        if not images:
            continue
        caption_edges = media.get("edge_media_to_caption", {}).get("edges") or []
        caption = caption_edges[0].get("node", {}).get("text", "") if caption_edges else ""
        published_at = media.get("taken_at_timestamp")
        if published_at:
            published_at = datetime.fromtimestamp(published_at).astimezone().isoformat()
        posts.append(
            {
                "instagram_media_id": media.get("id"),
                "collection_key": media.get("id") or shortcode,
                "caption": caption,
                "permalink": f"https://www.instagram.com/p/{shortcode}/",
                "published_at": published_at,
                "media": images,
            }
        )
    return posts


def public_embed_profile(handle):
    username = handle.lstrip("@").lower()
    request = Request(
        f"https://www.instagram.com/{username}/embed/", headers={"User-Agent": "Mozilla/5.0"}
    )
    with urlopen(request, timeout=20) as response:
        payload = response.read(2_000_000).decode("utf-8", "ignore")

    def decode_value(encoded):
        decoded = encoded
        for _ in range(2):
            try:
                decoded = json.loads('"' + decoded + '"')
            except (json.JSONDecodeError, TypeError):
                break
        return decoded

    def value(key):
        match = re.search(r'\\"' + re.escape(key) + r'\\":\\"(.*?)\\"', payload)
        return decode_value(match.group(1)) if match else None

    found = value("username")
    image_url = value("profile_pic_url")
    if found != username or not image_url:
        raise ValueError(f"Instagram profile not found: {handle}")

    def count(key):
        match = re.search(r'\\"' + re.escape(key) + r'\\":\{\\"count\\":(\d+)', payload)
        return int(match.group(1)) if match else None

    verified_match = re.search(r'\\"is_verified\\":(true|false)', payload)
    posts = extract_embed_posts(payload)
    media_grouping_version = INSTAGRAM_MEDIA_SYNC_VERSION if posts else 1
    if not posts:
        seen = set()
        pattern = re.compile(
            r'\\"shortcode\\":\\"(.*?)\\".*?\\"display_url\\":\\"(.*?)\\"', re.DOTALL
        )
        for shortcode_value, image_value in pattern.findall(payload):
            shortcode = decode_value(shortcode_value)
            post_image = decode_value(image_value)
            if shortcode in seen:
                continue
            seen.add(shortcode)
            posts.append(
                {"image_url": post_image, "permalink": f"https://www.instagram.com/p/{shortcode}/"}
            )
            if len(posts) == 9:
                break
    return {
        "name": value("full_name") or username,
        "avatar_url": image_url,
        "posts": posts,
        "biography": value("biography"),
        "followers_count": count("edge_followed_by"),
        "following_count": count("edge_follow"),
        "media_count": count("edge_owner_to_timeline_media"),
        "instagram_verified": verified_match and verified_match.group(1) == "true",
        "media_grouping_version": media_grouping_version,
    }


def instagram_profile(handle):
    if business_discovery_enabled():
        return business_discovery_profile(handle)
    profile = public_embed_profile(handle)
    profile["source"] = "instagram_public_embed"
    return profile
