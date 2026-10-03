from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.request import Request, urlopen

from backend.models.media import ImageCacheResult, InstagramImage, InstagramPost, InstagramProfile

MAX_IMAGE_BYTES = 8_000_000
IMAGE_DOWNLOAD_WORKERS = 6


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
        data = response.read(MAX_IMAGE_BYTES + 1)
        mime = detected_image_mime(data)
        if not mime or not data or len(data) > MAX_IMAGE_BYTES:
            raise ValueError("invalid image response")
        return data, mime


def cache_post_image(db, post_id, image_url):
    image_blob, mime_type = download_image(image_url)
    db.execute(
        """UPDATE merchant_posts SET image_blob=%s,mime_type=%s,
          image_cached_at=CURRENT_TIMESTAMP WHERE id=%s""",
        (image_blob, mime_type, post_id),
    )
    return True


def cache_merchant_avatar(db, merchant_id, image_url, source_url):
    avatar_blob, mime_type = download_image(image_url)
    db.execute(
        """UPDATE merchants SET avatar_blob=%s,avatar_mime_type=%s,
      avatar_source_url=%s,avatar_updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
        (avatar_blob, mime_type, source_url, merchant_id),
    )
    return mime_type


def ensure_gallery_images(db, handles=None) -> ImageCacheResult:
    """Cache actual remote post images; never fabricate gallery entries."""
    requested = list(handles or [])
    query = """SELECT p.id,p.image_url FROM merchant_posts p
               JOIN merchants m ON m.id=p.merchant_id
               WHERE (p.image_blob IS NULL OR p.mime_type IS NULL)"""
    params = ()
    if requested:
        query += " AND m.handle=ANY(%s)"
        params = (requested,)
    uncached = list(db.execute(query, params))
    for post in uncached:
        cache_post_image(db, post["id"], post["image_url"])
    return ImageCacheResult(
        attempted_images=len(uncached),
        cached_images=len(uncached),
        failed_images=0,
    )


@dataclass
class PostImage:
    post: InstagramPost
    image: InstagramImage


def replace_profile_posts(db, merchant_id: int, profile: InstagramProfile) -> int:
    candidates = [PostImage(post, image) for post in profile.posts for image in post.media]
    if not candidates:
        return 0

    workers = min(IMAGE_DOWNLOAD_WORKERS, len(candidates))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        downloaded = list(executor.map(download_post_image, candidates))
    db.execute("DELETE FROM merchant_posts WHERE merchant_id=%s", (merchant_id,))
    for flat_position, (candidate, image_blob, mime_type) in enumerate(downloaded, 1):
        insert_post_image(
            db, merchant_id, candidate, image_blob, mime_type, flat_position, profile.source
        )
    db.execute(
        """UPDATE merchants SET instagram_media_sync_version=GREATEST(
          instagram_media_sync_version,%s),instagram_media_synced_at=CURRENT_TIMESTAMP
          WHERE id=%s""",
        (profile.media_grouping_version, merchant_id),
    )
    return len(downloaded)


def download_post_image(candidate: PostImage):
    image_blob, mime_type = download_image(candidate.image.image_url)
    return candidate, image_blob, mime_type


def insert_post_image(db, merchant_id, candidate, image_blob, mime_type, position, source):
    post, image = candidate.post, candidate.image
    row = (
        image.instagram_media_id,
        post.caption,
        image.image_url,
        image_blob,
        mime_type,
        post.permalink,
        position,
        post.collection_key,
        image.media_position,
        post.published_at,
        source,
        post.permalink,
    )
    db.execute(
        """INSERT INTO merchant_posts(merchant_id,instagram_media_id,caption,image_url,image_blob,mime_type,permalink,position,collection_key,media_position,published_at,image_source,image_source_url,image_cached_at)
      VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP)""",
        (merchant_id, *row),
    )
