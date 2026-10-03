from concurrent.futures import ThreadPoolExecutor
from html import escape
from urllib.request import Request, urlopen

from backend.instagram import instagram_shortcode, normalize_identifier


def fallback_avatar(initial, color):
    safe_initial = escape(initial)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">
<rect width="256" height="256" rx="128" fill="{color}"/><circle cx="128" cy="128" r="104" fill="#fff" opacity=".28"/>
<path d="M75 184c12-35 32-53 53-53s41 18 53 53" fill="#fff" opacity=".48"/><circle cx="128" cy="91" r="35" fill="#fff" opacity=".48"/>
<text x="128" y="151" text-anchor="middle" font-family="Tahoma,sans-serif" font-size="72" font-weight="700" fill="#7f2e38">{safe_initial}</text>
</svg>'''
    return svg.encode("utf-8"), "image/svg+xml"


def detected_image_mime(data):
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def download_image(url):
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; KahooPrototype/1.0)"})
    with urlopen(request, timeout=20) as response:
        mime = response.headers.get_content_type()
        data = response.read(8_000_001)
        mime = mime if mime.startswith("image/") else detected_image_mime(data)
        if not mime or not data or len(data) > 8_000_000:
            raise ValueError("invalid image response")
        return data, mime


def cache_post_image(db, post_id, image_url):
    try:
        image_blob, mime_type = download_image(image_url)
    except (OSError, ValueError):
        return False
    db.execute(
        """UPDATE merchant_posts SET image_blob=%s,mime_type=%s,
          image_source=COALESCE(image_source,'curated_seed'),
          image_source_url=COALESCE(image_source_url,permalink),
          image_cached_at=CURRENT_TIMESTAMP WHERE id=%s""",
        (image_blob, mime_type, post_id),
    )
    return True


def cache_merchant_avatar(db, merchant_id, initial, color, image_url=None, source_url=None):
    if image_url:
        try:
            avatar_blob, mime_type = download_image(image_url)
        except (OSError, ValueError):
            return False
    else:
        avatar_blob, mime_type = fallback_avatar(initial, color)
        source_url = None
    db.execute(
        """UPDATE merchants SET avatar_blob=%s,avatar_mime_type=%s,
      avatar_source_url=%s,avatar_updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
        (avatar_blob, mime_type, source_url, merchant_id),
    )
    return mime_type


def ensure_gallery_images(db, handles=None):
    """Cache actual remote post images; never fabricate gallery entries."""
    requested = [normalize_identifier(handle) for handle in (handles or [])]
    query = """SELECT p.id,p.image_url FROM merchant_posts p
               JOIN merchants m ON m.id=p.merchant_id
               WHERE (p.image_blob IS NULL OR p.mime_type IS NULL)"""
    params = ()
    if requested:
        query += " AND m.handle=ANY(%s)"
        params = (requested,)
    uncached = list(db.execute(query, params))
    cached = sum(cache_post_image(db, post["id"], post["image_url"]) for post in uncached)
    return {
        "attempted_images": len(uncached),
        "cached_images": cached,
        "failed_images": len(uncached) - cached,
    }


def replace_profile_posts(db, merchant_id, label, profile):
    candidates = []
    source = profile.get("source", "instagram_public_embed")
    for post_position, post in enumerate(profile.get("posts", [])[:9], 1):
        media_items = post.get("media") or [
            {"image_url": post.get("image_url"), "media_position": 1}
        ]
        collection_key = (
            post.get("collection_key")
            or post.get("instagram_media_id")
            or instagram_shortcode(post.get("permalink"))
            or f"{merchant_id}-{post_position}"
        )
        for media in media_items:
            image_url = media.get("image_url")
            if not image_url:
                continue
            candidates.append(
                {
                    "instagram_media_id": media.get("instagram_media_id")
                    or post.get("instagram_media_id"),
                    "caption": post.get("caption", ""),
                    "image_url": image_url,
                    "permalink": post.get("permalink"),
                    "collection_key": collection_key,
                    "media_position": media.get("media_position", 1),
                    "published_at": post.get("published_at"),
                }
            )

    def fetch(candidate):
        try:
            image_blob, mime_type = download_image(candidate["image_url"])
            return candidate, image_blob, mime_type
        except (OSError, ValueError):
            return None

    workers = min(6, len(candidates)) or 1
    with ThreadPoolExecutor(max_workers=workers) as executor:
        downloaded = [item for item in executor.map(fetch, candidates) if item]
    if not downloaded:
        return 0
    db.execute("DELETE FROM merchant_posts WHERE merchant_id=%s", (merchant_id,))
    for flat_position, (post, image_blob, mime_type) in enumerate(downloaded, 1):
        row = (
            post["instagram_media_id"],
            post["caption"],
            post["image_url"],
            image_blob,
            mime_type,
            post["permalink"],
            flat_position,
            post["collection_key"],
            post["media_position"],
            post["published_at"],
            source,
            post["permalink"],
        )
        db.execute(
            """INSERT INTO merchant_posts(merchant_id,instagram_media_id,caption,image_url,image_blob,mime_type,permalink,position,collection_key,media_position,published_at,image_source,image_source_url,image_cached_at)
          VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)""",
            (merchant_id, *row),
        )
    return len(downloaded)
