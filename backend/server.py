#!/usr/bin/env python3
import hmac
import json
import logging
import math
import mimetypes
import os
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from html import escape
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

import psycopg

from backend.catalog import load_merchant_catalogs, merchant_catalog_paths
from backend.database import PROJECT_ROOT, connect, run_category_seed, run_migrations
from backend.instagram import business_discovery_enabled, business_discovery_profile
from backend.merchant_import import infer_category, normalize_identifier
from backend.search import (
    diversify_results,
    lexical_merchant_matches,
    merchant_quality_score,
    normalize_search,
    phrase_proximity_bonus,
    query_coverage,
    query_tokens,
    reciprocal_rank_fusion,
    semantic_merchant_scores,
    sync_search_documents,
    term_match_strength,
)

PUBLIC_ROOT = PROJECT_ROOT / "public"
DATA_ROOT = PROJECT_ROOT / "data"
INSTAGRAM_MEDIA_SYNC_VERSION = 2
logger = logging.getLogger(__name__)

MERCHANTS = json.loads((DATA_ROOT / "merchant_seed.json").read_text(encoding="utf-8"))
MERCHANT_CATEGORY_SEED = {item["handle"]: tuple(item["category_codes"]) for item in MERCHANTS}
CATALOG_PATHS = merchant_catalog_paths(DATA_ROOT)
CATALOG_SNAPSHOT_AT, CATALOG_MERCHANTS = load_merchant_catalogs(CATALOG_PATHS)
for catalog_merchant in CATALOG_MERCHANTS:
    extra_categories = catalog_merchant.get("category_codes", ())
    if extra_categories:
        existing_categories = MERCHANT_CATEGORY_SEED.get(catalog_merchant["handle"], ())
        MERCHANT_CATEGORY_SEED[catalog_merchant["handle"]] = tuple(
            dict.fromkeys((*existing_categories, *extra_categories))
        )


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


def ensure_gallery_images(db):
    """Cache actual remote post images; never fabricate gallery entries."""
    uncached = list(
        db.execute(
            """SELECT p.id,p.image_url FROM merchant_posts p
           WHERE p.image_blob IS NULL OR p.mime_type IS NULL"""
        )
    )
    cached = sum(cache_post_image(db, post["id"], post["image_url"]) for post in uncached)
    return {
        "attempted_images": len(uncached),
        "cached_images": cached,
        "failed_images": len(uncached) - cached,
    }


def merchant_media_needs(merchant, minimum_images=3):
    """Describe which locally stored Instagram assets still need backfilling."""
    needs_avatar = (
        not merchant.get("avatar_blob")
        or merchant.get("avatar_mime_type") == "image/svg+xml"
        or not (merchant.get("avatar_source_url") or "").startswith("http")
    )
    needs_posts = (merchant.get("cached_images") or 0) < minimum_images or (
        merchant.get("instagram_media_sync_version") or 0
    ) < INSTAGRAM_MEDIA_SYNC_VERSION
    return needs_avatar, needs_posts


def instagram_media_backfill_status(minimum_images=3, handles=None):
    """Return merchants whose profile picture or post gallery is incomplete."""
    requested = {normalize_identifier(handle) for handle in (handles or [])}
    incomplete = []
    for merchant in merchant_media_rows():
        if requested and merchant["handle"].lower() not in requested:
            continue
        needs_avatar, needs_posts = merchant_media_needs(merchant, minimum_images)
        if needs_avatar or needs_posts:
            incomplete.append(
                {
                    "id": merchant["id"],
                    "handle": merchant["handle"],
                    "missing_avatar": needs_avatar,
                    "missing_posts": needs_posts,
                    "cached_images": merchant["cached_images"] or 0,
                    "media_sync_version": merchant["instagram_media_sync_version"],
                }
            )
    return incomplete


def merchant_media_rows():
    with connect() as db:
        return list(
            db.execute("""SELECT m.id,m.handle,m.name,m.avatar_initial,
          m.avatar_color,m.description_source,m.avatar_blob,m.avatar_mime_type,
          m.avatar_source_url,m.instagram_media_sync_version,
          COUNT(p.id) FILTER (WHERE p.image_blob IS NOT NULL) cached_images
          FROM merchants m LEFT JOIN merchant_posts p ON p.merchant_id=m.id
          GROUP BY m.id ORDER BY m.id""")
        )


def seed_public_catalog(db):
    """Upsert the reviewed public-directory snapshot without claiming verification."""
    created = 0
    created_handles = []
    enriched = 0
    excluded_handles = {
        row["handle"] for row in db.execute("SELECT handle FROM merchant_exclusions")
    }
    for item in CATALOG_MERCHANTS:
        handle = item["handle"]
        if handle in excluded_handles:
            continue
        description_source = item.get("description_source", "curated_public_directory")
        metrics_source = item.get("metrics_source", "basaliro_public_directory")
        existing = db.execute(
            "SELECT id,avatar_blob FROM merchants WHERE handle=%s", (handle,)
        ).fetchone()
        if existing:
            merchant_id = existing["id"]
            enriched += 1
            if item.get("is_new"):
                db.execute(
                    """UPDATE merchants SET
                      name=CASE WHEN description_source='user_submitted_profile_url'
                        AND biography_source IS NOT NULL THEN name ELSE %s END,
                      description=CASE WHEN description_source='llm' THEN description ELSE %s END,
                      description_source=CASE WHEN description_source='llm' THEN description_source ELSE %s END,
                      description_source_url=CASE WHEN description_source='llm' THEN description_source_url ELSE %s END,
                      category_code=%s,city=%s,source_url=%s,updated_label='داده عمومی'
                      WHERE id=%s""",
                    (
                        item["name"],
                        item["description"],
                        description_source,
                        item["source_url"],
                        item["category_code"],
                        item["city"],
                        item["source_url"],
                        merchant_id,
                    ),
                )
        else:
            username = handle[1:]
            name = item["name"]
            source_url = item["source_url"]
            cursor = db.execute(
                """INSERT INTO merchants(
                  instagram_id,name,handle,description,description_source,
                  description_source_url,description_updated_at,source_url,
                  category_code,city,avatar_initial,avatar_color,instagram_url,
                  updated_label,verified,followers_count,media_count,
                  metrics_source,metrics_source_url,metrics_updated_at)
                  VALUES(%s,%s,%s,%s,%s,%s,%s,%s, %s,%s,%s,%s,%s,'داده عمومی',0,%s,%s,
                    %s,%s,%s) RETURNING id""",
                (
                    f"catalog_{username}",
                    name,
                    handle,
                    item["description"],
                    description_source,
                    source_url,
                    CATALOG_SNAPSHOT_AT,
                    source_url,
                    item["category_code"],
                    item["city"],
                    name[0],
                    "#e3e7e1",
                    f"https://www.instagram.com/{username}/",
                    item.get("followers_count"),
                    item.get("media_count"),
                    metrics_source,
                    item.get("metrics_source_url"),
                    CATALOG_SNAPSHOT_AT,
                ),
            )
            merchant_id = cursor.fetchone()["id"]
            created += 1
            created_handles.append(handle)
            cache_merchant_avatar(db, merchant_id, name[0], "#e3e7e1")

        if item.get("metrics_source_url"):
            db.execute(
                """UPDATE merchants SET
                  followers_count=COALESCE(%s,followers_count),
                  media_count=COALESCE(%s,media_count),
                  metrics_source=%s,
                  metrics_source_url=%s,metrics_updated_at=%s
                  WHERE id=%s AND (metrics_updated_at IS NULL OR metrics_updated_at<=%s)""",
                (
                    item.get("followers_count"),
                    item.get("media_count"),
                    metrics_source,
                    item["metrics_source_url"],
                    CATALOG_SNAPSHOT_AT,
                    merchant_id,
                    CATALOG_SNAPSHOT_AT,
                ),
            )
        if item.get("quality_score") is not None:
            db.execute(
                """UPDATE merchants SET directory_quality_score=%s,
                  directory_review_count=%s,quality_source=%s,quality_source_url=%s,
                  quality_updated_at=%s WHERE id=%s""",
                (
                    item["quality_score"],
                    item.get("review_count", 0),
                    item.get("quality_source", "basaliro_ai_trust"),
                    item.get("quality_source_url", item.get("source_url")),
                    CATALOG_SNAPSHOT_AT,
                    merchant_id,
                ),
            )
    return {
        "created": created,
        "created_handles": created_handles,
        "enriched": enriched,
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


def initialize_database():
    run_migrations()
    run_category_seed(DATA_ROOT / "categories.sql")
    if os.environ.get("KAHOO_SEED_DEMO", "1").lower() not in {"1", "true", "yes"}:
        return
    with connect() as db:
        excluded_handles = {
            row["handle"] for row in db.execute("SELECT handle FROM merchant_exclusions")
        }
        for item in MERCHANTS:
            instagram_id, name, handle = item["instagram_id"], item["name"], item["handle"]
            description, category, city = item["description"], item["category_code"], item["city"]
            initial, color = item["avatar_initial"], item["avatar_color"]
            updated, verified, source = item["updated_label"], item["verified"], item["source_url"]
            posts = item["photos"]
            if handle in excluded_handles:
                continue
            url = f"https://www.instagram.com/{handle[1:]}/"
            existing = db.execute(
                "SELECT id FROM merchants WHERE instagram_id=%s", (instagram_id,)
            ).fetchone()
            if existing:
                merchant_id = existing["id"]
                db.execute(
                    "UPDATE merchants SET name=%s,handle=%s,description=CASE WHEN description_source='llm' THEN description ELSE %s END,category_code=%s,city=%s,avatar_initial=%s,avatar_color=%s,instagram_url=%s,updated_label=%s,verified=%s,verification_source=%s,verified_at=CURRENT_DATE WHERE id=%s",
                    (
                        name,
                        handle,
                        description,
                        category,
                        city,
                        initial,
                        color,
                        url,
                        updated,
                        verified,
                        source,
                        merchant_id,
                    ),
                )
            else:
                cursor = db.execute(
                    "INSERT INTO merchants(instagram_id,name,handle,description,category_code,city,avatar_initial,avatar_color,instagram_url,updated_label,verified,verification_source,verified_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,CURRENT_DATE) RETURNING id",
                    (
                        instagram_id,
                        name,
                        handle,
                        description,
                        category,
                        city,
                        initial,
                        color,
                        url,
                        updated,
                        verified,
                        source,
                    ),
                )
                merchant_id = cursor.fetchone()["id"]
            db.execute(
                """UPDATE merchants SET source_url=%s,description_source=COALESCE(description_source,'curated_seed'),
              description_source_url=COALESCE(description_source_url,%s),description_updated_at=COALESCE(description_updated_at,CURRENT_TIMESTAMP)
              WHERE id=%s""",
                (source, source, merchant_id),
            )
            if item.get("biography"):
                db.execute(
                    """UPDATE merchants SET biography=%s,biography_source=%s,biography_updated_at=CURRENT_TIMESTAMP
                  WHERE id=%s AND biography_source IS NULL""",
                    (item["biography"], item["biography_source"], merchant_id),
                )
            avatar = db.execute(
                "SELECT avatar_blob,avatar_mime_type,avatar_source_url FROM merchants WHERE id=%s",
                (merchant_id,),
            ).fetchone()
            post_state = db.execute(
                "SELECT COUNT(*) count,COUNT(*) FILTER (WHERE POSITION('cdninstagram.com' IN image_url)>0) instagram_count FROM merchant_posts WHERE merchant_id=%s",
                (merchant_id,),
            ).fetchone()
            needs_avatar = (
                not avatar["avatar_blob"]
                or avatar["avatar_mime_type"] == "image/svg+xml"
                or not avatar["avatar_source_url"]
            )
            needs_posts = (
                post_state["count"] < 6
                or (post_state["instagram_count"] or 0) < post_state["count"]
            )
            profile = None
            if os.environ.get("KAHOO_SYNC_ON_START", "0").lower() in {"1", "true", "yes"} and (
                needs_avatar or needs_posts
            ):
                try:
                    profile = instagram_profile(handle)
                except (OSError, ValueError):
                    logger.exception("Could not refresh Instagram profile %s", handle)
            if profile and profile.get("avatar_url"):
                avatar_saved = cache_merchant_avatar(
                    db, merchant_id, initial, color, profile["avatar_url"], profile["avatar_url"]
                )
                if not avatar_saved and not avatar["avatar_blob"]:
                    cache_merchant_avatar(db, merchant_id, initial, color)
            elif not avatar["avatar_blob"]:
                cache_merchant_avatar(db, merchant_id, initial, color)
            if needs_posts and profile and len(profile["posts"]) >= 4:
                replace_profile_posts(db, merchant_id, name, profile)
            if (
                db.execute(
                    "SELECT COUNT(*) FROM merchant_posts WHERE merchant_id=%s", (merchant_id,)
                ).fetchone()["count"]
                == 0
            ):
                for position, photo in enumerate(posts, 1):
                    image_url = (
                        f"https://images.unsplash.com/{photo}?auto=format&fit=crop&w=500&q=80"
                    )
                    db.execute(
                        "INSERT INTO merchant_posts(merchant_id,image_url,permalink,position) VALUES(%s,%s,%s,%s)",
                        (merchant_id, image_url, url, position),
                    )
        seed_public_catalog(db)
        ensure_gallery_images(db)
        seed_search_metadata(db)
        sync_search_documents(db)


def refresh_instagram_profiles(
    handles=None, on_result=None, on_start=None, only_missing=False, minimum_images=3, limit=None
):
    requested = {normalize_identifier(handle) for handle in (handles or [])}
    results = []
    selected = []
    for merchant in merchant_media_rows():
        if requested and merchant["handle"].lower() not in requested:
            continue
        needs_avatar, needs_posts = merchant_media_needs(merchant, minimum_images)
        if only_missing and not (needs_avatar or needs_posts):
            continue
        selected.append((merchant, needs_avatar, needs_posts))
    if limit is not None and limit > 0:
        selected = selected[:limit]
    for merchant, needs_avatar, needs_posts in selected:
        if on_start:
            on_start(merchant["handle"])
        try:
            profile = instagram_profile(merchant["handle"])
            profile_name = (profile.get("name") or "").strip()
            display_name = (
                profile_name
                if merchant["description_source"] == "user_submitted_profile_url" and profile_name
                else merchant["name"]
            )
            with connect() as db:
                biography = (profile.get("biography") or "").strip()
                source = profile.get("source", "instagram_public_embed")
                db.execute(
                    """UPDATE merchants SET name=%s,avatar_initial=%s,
                  biography=%s,biography_source=%s,
                  biography_updated_at=CURRENT_TIMESTAMP,followers_count=COALESCE(%s,followers_count),
                  following_count=COALESCE(%s,following_count),media_count=COALESCE(%s,media_count),
                  metrics_source=%s,metrics_source_url=%s,metrics_updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
                    (
                        display_name,
                        display_name[0],
                        biography,
                        source,
                        profile.get("followers_count"),
                        profile.get("following_count"),
                        profile.get("media_count"),
                        source,
                        f"https://www.instagram.com/{merchant['handle'][1:]}/",
                        merchant["id"],
                    ),
                )
                avatar_saved = False
                if profile.get("avatar_url") and (not only_missing or needs_avatar):
                    avatar_saved = bool(
                        cache_merchant_avatar(
                            db,
                            merchant["id"],
                            display_name[0],
                            merchant["avatar_color"],
                            profile["avatar_url"],
                            profile["avatar_url"],
                        )
                    )
                posts_saved = (
                    replace_profile_posts(db, merchant["id"], display_name, profile)
                    if profile.get("posts") and (not only_missing or needs_posts)
                    else 0
                )
                if posts_saved:
                    db.execute(
                        """UPDATE merchants SET
                      instagram_media_sync_version=GREATEST(instagram_media_sync_version,%s),
                      instagram_media_synced_at=CURRENT_TIMESTAMP WHERE id=%s""",
                        (profile.get("media_grouping_version", 1), merchant["id"]),
                    )
            result = {
                "handle": merchant["handle"],
                "updated": True,
                "source": source,
                "posts_found": len(profile.get("posts", [])),
                "images_saved": posts_saved,
                "avatar_saved": avatar_saved,
                "has_biography": bool(biography),
                "needed_avatar": needs_avatar,
                "needed_posts": needs_posts,
            }
        except Exception as error:
            result = {"handle": merchant["handle"], "updated": False, "error": str(error)}
        results.append(result)
        if on_result:
            on_result(result)
    with connect() as db:
        seed_search_metadata(db)
        sync_search_documents(db)
    return results


def refresh_instagram_avatars(handles=None, on_result=None):
    """Replace missing/generated avatars with the shops' current profile images."""
    requested = {normalize_identifier(handle) for handle in (handles or [])}
    results = []
    with connect() as db:
        rows = list(
            db.execute("""SELECT id,handle,avatar_initial,avatar_color,
          avatar_blob,avatar_mime_type,avatar_source_url FROM merchants ORDER BY id""")
        )
    for merchant in rows:
        if requested and merchant["handle"] not in requested:
            continue
        has_remote_avatar = (
            bool(merchant["avatar_blob"])
            and merchant["avatar_mime_type"] != "image/svg+xml"
            and (merchant["avatar_source_url"] or "").startswith("http")
        )
        if not requested and has_remote_avatar:
            continue
        try:
            profile = instagram_profile(merchant["handle"])
            avatar_url = profile.get("avatar_url")
            if not avatar_url:
                raise ValueError("Instagram returned no profile picture")
            with connect() as db:
                avatar_saved = cache_merchant_avatar(
                    db,
                    merchant["id"],
                    merchant["avatar_initial"],
                    merchant["avatar_color"],
                    avatar_url,
                    avatar_url,
                )
            if not avatar_saved:
                raise ValueError("Profile picture download failed")
            result = {"handle": merchant["handle"], "updated": True, "mime_type": avatar_saved}
        except Exception as error:
            result = {"handle": merchant["handle"], "updated": False, "error": str(error)}
        results.append(result)
        if on_result:
            on_result(result)
    return results


def catalog_profiles_missing_posts(minimum_images=3):
    """Return catalog shops whose database gallery is still incomplete."""
    catalog_handles = {item["handle"] for item in CATALOG_MERCHANTS if item.get("is_new")}
    with connect() as db:
        rows = db.execute("""SELECT m.handle,m.instagram_media_sync_version,
          COUNT(p.id) FILTER (WHERE p.image_blob IS NOT NULL) cached_images
          FROM merchants m LEFT JOIN merchant_posts p ON p.merchant_id=m.id
          GROUP BY m.id,m.handle,m.instagram_media_sync_version ORDER BY m.id""")
        missing = [
            row["handle"]
            for row in rows
            if row["handle"] in catalog_handles
            and (
                (row["cached_images"] or 0) < minimum_images
                or row["instagram_media_sync_version"] < INSTAGRAM_MEDIA_SYNC_VERSION
            )
        ]
        shared_handles = {
            item["handle"]
            for item in CATALOG_MERCHANTS
            if item.get("description_source") == "user_submitted_profile_url"
        }
        return sorted(missing, key=lambda handle: handle not in shared_handles)


def category_tree():
    with connect() as db:
        rows = [
            dict(row)
            for row in db.execute(
                "SELECT code,parent_code,level,label_fa,label_en,icon FROM categories ORDER BY level,sort_order,label_fa"
            )
        ]
        counts = {row["code"]: 0 for row in rows}
        parents = {row["code"]: row["parent_code"] for row in rows}
        assignments = {}
        for item in db.execute("SELECT merchant_id,category_code FROM merchant_categories"):
            assignments.setdefault(item["merchant_id"], []).append(item["category_code"])
        for category_codes in assignments.values():
            visible = set()
            for category_code in category_codes:
                code = category_code
                while code:
                    visible.add(code)
                    code = parents.get(code)
            for code in visible:
                counts[code] = counts.get(code, 0) + 1
        nodes = {row["code"]: {**row, "count": counts[row["code"]], "children": []} for row in rows}
        roots = []
        for row in rows:
            node = nodes[row["code"]]
            (nodes[row["parent_code"]]["children"] if row["parent_code"] else roots).append(node)
        return roots


SEARCH_ALIAS_SEED = (
    ("شلوار", "لباس", 0.55, "curated_taxonomy"),
    ("شلوار", "پوشاک", 0.55, "curated_taxonomy"),
    ("شلوار", "پایین تنه", 0.9, "curated_taxonomy"),
    ("جین", "شلوار", 0.9, "curated_taxonomy"),
    ("لگ", "شلوار", 0.8, "curated_taxonomy"),
    ("شلوارک", "شلوار", 0.85, "curated_taxonomy"),
    ("تی شرت", "تیشرت", 0.95, "curated_taxonomy"),
    ("تیشرت", "لباس", 0.6, "curated_taxonomy"),
    ("گوشی", "موبایل", 0.95, "curated_taxonomy"),
    ("تلفن همراه", "موبایل", 0.95, "curated_taxonomy"),
    ("اسمارت فون", "موبایل", 0.85, "curated_taxonomy"),
    ("کاور", "قاب", 0.95, "curated_taxonomy"),
    ("کیس", "قاب", 0.9, "curated_taxonomy"),
    ("قاب", "لوازم جانبی موبایل", 0.8, "curated_taxonomy"),
    ("میکاپ", "آرایشی", 0.95, "curated_taxonomy"),
    ("لوازم آرایش", "آرایشی", 0.95, "curated_taxonomy"),
    ("اسکین کر", "مراقبت پوست", 0.9, "curated_taxonomy"),
    ("ادکلن", "عطر", 0.95, "curated_taxonomy"),
    ("کتونی", "کفش", 0.95, "curated_taxonomy"),
    ("اسنیکر", "کفش", 0.85, "curated_taxonomy"),
    ("نوشت افزار", "لوازم تحریر", 0.95, "curated_taxonomy"),
    ("استیشنری", "لوازم تحریر", 0.85, "curated_taxonomy"),
    ("پت شاپ", "حیوانات خانگی", 0.95, "curated_taxonomy"),
    ("عروسک", "اسباب بازی", 0.85, "curated_taxonomy"),
    ("هوم دکور", "دکوراسیون", 0.85, "curated_taxonomy"),
    ("مبایل", "موبایل", 0.95, "curated_typo"),
    ("موبایل", "گوشی", 0.7, "curated_taxonomy"),
    ("لوازم جانبی گوشی", "لوازم جانبی موبایل", 0.95, "curated_taxonomy"),
    ("ارایشی", "آرایشی", 0.95, "curated_typo"),
    ("لوازم ارایش", "لوازم آرایشی", 0.95, "curated_typo"),
    ("کازمتیک", "آرایشی", 0.85, "curated_taxonomy"),
    ("اسکینکر", "مراقبت پوست", 0.95, "curated_taxonomy"),
    ("ضد افتاب", "ضدآفتاب", 0.95, "curated_typo"),
    ("کفش اسپرت", "کتونی", 0.9, "curated_taxonomy"),
    ("اسنیکرز", "کتونی", 0.9, "curated_taxonomy"),
    ("نیم بوت", "بوت", 0.9, "curated_taxonomy"),
    ("مانتو", "پوشاک زنانه", 0.9, "curated_taxonomy"),
    ("شومیز", "پوشاک زنانه", 0.9, "curated_taxonomy"),
    ("روسری", "پوشاک زنانه", 0.8, "curated_taxonomy"),
    ("شال", "پوشاک زنانه", 0.75, "curated_taxonomy"),
    ("کراپ", "بالاپوش زنانه", 0.85, "curated_taxonomy"),
    ("هودی", "بالاپوش", 0.85, "curated_taxonomy"),
    ("کیف دستی", "کیف زنانه", 0.9, "curated_taxonomy"),
    ("اکسسوری", "زیورآلات", 0.75, "curated_taxonomy"),
    ("بدلیجات", "زیورآلات", 0.9, "curated_taxonomy"),
    ("خونه", "خانه", 0.9, "curated_typo"),
    ("اشپزخانه", "آشپزخانه", 0.95, "curated_typo"),
    ("لوازم التحریر", "لوازم تحریر", 0.95, "curated_typo"),
    ("غذای گربه", "پت شاپ", 0.9, "curated_taxonomy"),
    ("غذای سگ", "پت شاپ", 0.9, "curated_taxonomy"),
    ("سیسمونی", "کودک و نوزاد", 0.85, "curated_taxonomy"),
)


def searchable_tokens(text):
    return set(query_tokens(text))


def seed_search_metadata(db):
    for alias, term, weight, source in SEARCH_ALIAS_SEED:
        db.execute(
            """INSERT INTO search_aliases(alias,normalized_alias,term,normalized_term,weight,source)
            VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(normalized_alias,normalized_term)
            DO UPDATE SET alias=excluded.alias,term=excluded.term,weight=excluded.weight,source=excluded.source""",
            (alias, normalize_search(alias), term, normalize_search(term), weight, source),
        )
    for merchant in db.execute(
        "SELECT id,handle,category_code,description,description_source_url,biography,biography_source,instagram_url FROM merchants"
    ):
        db.execute(
            "DELETE FROM merchant_categories WHERE merchant_id=%s AND source IN ('merchant_primary','curated_catalog')",
            (merchant["id"],),
        )
        db.execute(
            """INSERT INTO merchant_categories(merchant_id,category_code,confidence,source,source_url)
            VALUES(%s,%s,1,'merchant_primary',%s) ON CONFLICT(merchant_id,category_code)
            DO UPDATE SET confidence=1,source='merchant_primary',source_url=excluded.source_url""",
            (merchant["id"], merchant["category_code"], merchant["description_source_url"]),
        )
        for category_code in MERCHANT_CATEGORY_SEED.get(merchant["handle"], ()):
            if category_code == merchant["category_code"]:
                continue
            db.execute(
                """INSERT INTO merchant_categories(merchant_id,category_code,confidence,source,source_url)
                VALUES(%s,%s,0.9,'curated_catalog',%s) ON CONFLICT(merchant_id,category_code)
                DO UPDATE SET confidence=excluded.confidence,source=excluded.source,source_url=excluded.source_url""",
                (merchant["id"], category_code, merchant["description_source_url"]),
            )
        db.execute(
            "DELETE FROM merchant_search_terms WHERE merchant_id=%s AND source IN ('description','biography')",
            (merchant["id"],),
        )
        sources = (
            ("description", merchant["description"], 1.0, merchant["description_source_url"]),
            ("biography", merchant["biography"], 0.8, merchant["instagram_url"]),
        )
        for source, text, weight, source_url in sources:
            for term in searchable_tokens(text):
                db.execute(
                    """INSERT INTO merchant_search_terms(merchant_id,term,normalized_term,weight,source,source_url,confidence)
                    VALUES(%s,%s,%s,%s,%s,%s,1) ON CONFLICT(merchant_id,normalized_term,source)
                    DO UPDATE SET term=excluded.term,weight=excluded.weight,source_url=excluded.source_url,updated_at=CURRENT_TIMESTAMP""",
                    (merchant["id"], term, term, weight, source, source_url),
                )


def save_llm_enrichment(merchant_id, description, terms, model, source_url, confidence=0.75):
    if not model or not source_url:
        raise ValueError("LLM enrichment requires both model and source_url provenance")
    normalized_terms = {
        normalize_search(term): term.strip() for term in terms if normalize_search(term)
    }
    with connect() as db:
        db.execute(
            """UPDATE merchants SET description=%s,description_source='llm',description_source_url=%s,
          description_generated_by=%s,description_updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
            (description.strip(), source_url, model, merchant_id),
        )
        db.execute(
            "DELETE FROM merchant_search_terms WHERE merchant_id=%s AND source='llm'",
            (merchant_id,),
        )
        for normalized, term in normalized_terms.items():
            db.execute(
                """INSERT INTO merchant_search_terms
              (merchant_id,term,normalized_term,weight,source,source_url,generated_by,confidence)
              VALUES(%s,%s,%s,1,'llm',%s,%s,%s)""",
                (merchant_id, term, normalized, source_url, model, max(0, min(1, confidence))),
            )
        seed_search_metadata(db)
        sync_search_documents(db)


def instagram_shortcode(permalink):
    match = re.search(r"/(?:p|reel)/([^/?#]+)", permalink or "")
    return match.group(1) if match else ""


def shared_prefix(left, right):
    length = 0
    for left_char, right_char in zip(left, right):
        if left_char != right_char:
            break
        length += 1
    return left[:length]


def merchant_posts(db, merchant_id):
    rows = list(
        db.execute(
            "SELECT id,image_url,permalink,position,collection_key,media_position FROM merchant_posts "
            "WHERE merchant_id=%s AND image_blob IS NOT NULL ORDER BY position,media_position",
            (merchant_id,),
        )
    )
    posts = []
    index = 0
    while index < len(rows):
        first = rows[index]
        end = index + 1
        collection_key = first["collection_key"]
        if collection_key:
            while end < len(rows) and rows[end]["collection_key"] == collection_key:
                end += 1
        elif end < len(rows) and first["image_url"] == rows[end]["image_url"]:
            prefix = shared_prefix(
                instagram_shortcode(first["permalink"]), instagram_shortcode(rows[end]["permalink"])
            )
            if len(prefix) >= 3:
                end += 1
                while end < len(rows) and instagram_shortcode(rows[end]["permalink"]).startswith(
                    prefix
                ):
                    end += 1
        collection = []
        seen_images = set()
        for media in rows[index:end]:
            if media["image_url"] in seen_images:
                continue
            seen_images.add(media["image_url"])
            collection.append(
                {"media_url": f"/api/media/{media['id']}", "position": len(collection) + 1}
            )
        shortcode = instagram_shortcode(first["permalink"])
        posts.append(
            {
                "post_id": first["id"],
                "key": collection_key or shortcode or f"{merchant_id}-{first['position']}",
                "permalink": first["permalink"],
                "position": len(posts) + 1,
                "media_url": collection[0]["media_url"],
                "media": collection,
                "image_count": len(collection),
            }
        )
        index = end
    return posts


def merchant_avatar_url(merchant):
    updated_at = merchant.get("avatar_updated_at")
    if isinstance(updated_at, datetime):
        version = str(int(updated_at.timestamp() * 1_000_000))
    else:
        version = re.sub(r"[^0-9]", "", str(updated_at or "0")) or "0"
    return f"/api/avatars/{merchant['id']}?v={version}"


def merchants(category=None, query=""):
    params = []
    where = []
    if category:
        where.append("""EXISTS (SELECT 1 FROM merchant_categories mc WHERE mc.merchant_id=m.id
          AND mc.category_code IN (WITH RECURSIVE branch(code) AS (SELECT %s UNION ALL
          SELECT c.code FROM categories c JOIN branch b ON c.parent_code=b.code) SELECT code FROM branch))""")
        params.append(category)
    sql = (
        "SELECT m.* FROM merchants m"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY m.id DESC"
    )
    with connect() as db:
        category_rows = {
            row["code"]: dict(row)
            for row in db.execute("SELECT code,parent_code,label_fa,label_en FROM categories")
        }
        categories_by_merchant = {}
        for item in db.execute("SELECT merchant_id,category_code FROM merchant_categories"):
            categories_by_merchant.setdefault(item["merchant_id"], []).append(item["category_code"])
        terms_by_merchant = {}
        for item in db.execute(
            "SELECT merchant_id,normalized_term,weight,confidence FROM merchant_search_terms"
        ):
            terms_by_merchant.setdefault(item["merchant_id"], []).append(
                (item["normalized_term"], item["weight"] * item["confidence"])
            )
        phrase = normalize_search(query)[:120]
        tokens = query_tokens(phrase)
        expanded = {token: 1.0 for token in tokens}
        alias_keys = set(tokens)
        if phrase:
            alias_keys.add(phrase)
        if alias_keys:
            placeholders = ",".join("%s" for _ in alias_keys)
            for item in db.execute(
                f"SELECT normalized_term,weight FROM search_aliases WHERE normalized_alias IN ({placeholders})",
                tuple(alias_keys),
            ):
                expanded[item["normalized_term"]] = max(
                    expanded.get(item["normalized_term"], 0), item["weight"]
                )
        lexical_matches = lexical_merchant_matches(db, phrase) if phrase else {}
        lexical_document_scores = {
            merchant_id: match["score"] for merchant_id, match in lexical_matches.items()
        }
        try:
            with db.transaction():
                semantic_scores = semantic_merchant_scores(db, phrase) if phrase else {}
        except (OSError, ValueError, psycopg.Error):
            logger.exception("Semantic search failed")
            semantic_scores = {}
        fused_scores = reciprocal_rank_fusion(lexical_document_scores, semantic_scores)
        click_counts = {
            row["merchant_id"]: row["clicks"]
            for row in db.execute(
                """SELECT merchant_id,COUNT(*) clicks FROM analytics_events
             WHERE event_type='merchant_click' AND merchant_id IS NOT NULL
               AND created_at>=CURRENT_TIMESTAMP-INTERVAL '30 days'
             GROUP BY merchant_id"""
            )
        }
        query_click_counts = {}
        if phrase:
            query_click_counts = {
                row["merchant_id"]: row["clicks"]
                for row in db.execute(
                    """SELECT merchant_id,COUNT(*) clicks FROM analytics_events
                 WHERE event_type='merchant_click' AND merchant_id IS NOT NULL
                   AND created_at>=CURRENT_TIMESTAMP-INTERVAL '90 days'
                   AND LOWER(query)=LOWER(%s) GROUP BY merchant_id""",
                    (query,),
                )
            }
        result = []
        for row in db.execute(sql, params):
            merchant = dict(row)
            score = 0
            exact_score = 0
            match_fields = set()
            fuzzy_match = False
            quality_score = merchant_quality_score(merchant, click_counts.get(row["id"], 0))
            if query:
                category_labels = []
                for category_code in categories_by_merchant.get(row["id"], [row["category_code"]]):
                    code = category_code
                    while code and code in category_rows:
                        category_labels.extend(
                            (category_rows[code]["label_fa"], category_rows[code]["label_en"])
                        )
                        code = category_rows[code]["parent_code"]
                identity = normalize_search(f"{row['name']} {row['handle']}")
                city = normalize_search(row["city"])
                description = normalize_search(row["description"])
                biography = normalize_search(row["biography"])
                category_text = normalize_search(" ".join(category_labels))
                stored_terms = terms_by_merchant.get(row["id"], [])

                def term_score(term, record_fields=False):
                    nonlocal fuzzy_match
                    strengths = {
                        "name": term_match_strength(term, identity),
                        "description": term_match_strength(term, description),
                        "biography": term_match_strength(term, biography),
                        "category": term_match_strength(term, category_text),
                        "city": term_match_strength(term, city),
                    }
                    metadata = max(
                        (
                            weight * term_match_strength(term, stored)
                            for stored, weight in stored_terms
                        ),
                        default=0,
                    )
                    if record_fields:
                        match_fields.update(
                            field for field, strength in strengths.items() if strength >= 0.7
                        )
                        if metadata >= 0.7:
                            match_fields.add("metadata")
                        fuzzy_match = fuzzy_match or any(
                            0 < strength < 0.7 for strength in strengths.values()
                        )
                    return (
                        14 * strengths["name"]
                        + 7 * strengths["description"]
                        + 5 * strengths["biography"]
                        + 9 * strengths["category"]
                        + 3 * strengths["city"]
                        + 6 * metadata
                    )

                token_scores = [term_score(token, True) for token in tokens]
                exact_score = sum(token_scores)
                related_score = sum(
                    term_score(term) * weight
                    for term, weight in expanded.items()
                    if term not in tokens
                )
                semantic_score = semantic_scores.get(row["id"], 0)
                document_score = lexical_document_scores.get(row["id"], 0)
                proximity = max(
                    phrase_proximity_bonus(phrase, identity),
                    phrase_proximity_bonus(phrase, category_text),
                    phrase_proximity_bonus(phrase, description),
                    phrase_proximity_bonus(phrase, biography),
                )
                phrase_bonus = (
                    20 * term_match_strength(phrase, identity)
                    + 13 * term_match_strength(phrase, description)
                    + 9 * term_match_strength(phrase, biography)
                    + 14 * term_match_strength(phrase, category_text)
                    + 10 * proximity
                )
                coverage = query_coverage(
                    tokens,
                    identity,
                    category_text,
                    description,
                    biography,
                    city,
                    " ".join(term for term, _ in stored_terms),
                )
                behavior_boost = min(2.0, math.log1p(query_click_counts.get(row["id"], 0)) * 0.7)
                score = (
                    exact_score
                    + related_score
                    + phrase_bonus
                    + fused_scores.get(row["id"], 0) * 300
                    + coverage * 8
                    + behavior_boost
                    + quality_score * 0.15
                )
                required_matches = max(2, (len(tokens) + 1) // 2)
                weak_lexical = (
                    len(tokens) > 1 and sum(value > 0 for value in token_scores) < required_matches
                )
                no_strong_signal = (
                    exact_score + related_score + phrase_bonus == 0
                    and semantic_score < 0.55
                    and document_score < 0.25
                )
                if (
                    not tokens
                    or score == 0
                    or no_strong_signal
                    or (weak_lexical and semantic_score < 0.55 and document_score < 0.25)
                ):
                    continue
                if "name" in match_fields:
                    reason = "نام فروشگاه"
                elif lexical_matches.get(row["id"], {}).get("entity_type") == "post":
                    reason = "محصول یا پست مرتبط"
                elif "category" in match_fields:
                    reason = "دسته‌بندی مرتبط"
                elif "description" in match_fields or "metadata" in match_fields:
                    reason = "محصولات مرتبط"
                elif "biography" in match_fields:
                    reason = "بیوی فروشگاه"
                elif "city" in match_fields:
                    reason = "موقعیت فروشگاه"
                elif semantic_score >= 0.55:
                    reason = "نتیجه معنایی نزدیک"
                else:
                    reason = "عبارت مشابه"
                merchant["match_reason"] = reason
                merchant["match_quality"] = (
                    "near"
                    if fuzzy_match and not match_fields
                    else "semantic"
                    if not match_fields and semantic_score >= 0.55
                    else "related"
                    if related_score and not exact_score
                    else "exact"
                )
                merchant["match_coverage"] = round(coverage, 2)
                lexical_match = lexical_matches.get(row["id"])
                if lexical_match and lexical_match["entity_type"] == "post":
                    merchant["matched_post_id"] = lexical_match["entity_id"]
            else:
                score = quality_score
            merchant.pop("avatar_blob", None)
            merchant.pop("avatar_mime_type", None)
            merchant["avatar_url"] = merchant_avatar_url(merchant)
            merchant["posts"] = merchant_posts(db, row["id"])
            if merchant.get("matched_post_id"):
                merchant["posts"].sort(
                    key=lambda post: post["post_id"] != merchant["matched_post_id"]
                )
            merchant["search_score"] = round(score, 2)
            result.append(merchant)
        ranked = sorted(
            result, key=lambda merchant: (merchant["search_score"], merchant["id"]), reverse=True
        )
        return diversify_results(ranked) if not query and not category else ranked


def search_suggestions(query, limit=8):
    phrase = normalize_search(query)[:80]
    if len(phrase) < 2:
        return []
    candidates = {}

    def add(value, label, kind, base=0):
        normalized = normalize_search(value)
        if not normalized:
            return
        strength = term_match_strength(phrase, normalized)
        if normalized == phrase:
            match = 100
        elif normalized.startswith(phrase):
            match = 85
        elif any(word.startswith(phrase) for word in normalized.split()):
            match = 75
        elif phrase in normalized:
            match = 65
        elif strength:
            match = 40 * strength
        else:
            return
        score = match + base
        previous = candidates.get(normalized)
        if not previous or score > previous[0]:
            candidates[normalized] = (score, {"value": value, "label": label, "type": kind})

    with connect() as db:
        for row in db.execute("SELECT name,handle FROM merchants"):
            add(row["name"], f"{row['name']} · {row['handle']}", "merchant", 8)
            add(row["handle"].lstrip("@"), f"{row['name']} · {row['handle']}", "merchant", 7)
        category_pattern = f"%{phrase}%"
        for row in db.execute(
            """SELECT label_fa FROM categories
          WHERE level>=2 AND (label_fa ILIKE %s OR label_en ILIKE %s)
          ORDER BY level,sort_order LIMIT 100""",
            (category_pattern, category_pattern),
        ):
            add(row["label_fa"], row["label_fa"], "category", 5)
        for row in db.execute("SELECT alias,term,weight FROM search_aliases"):
            add(row["term"], row["term"], "query", float(row["weight"]) * 5)
            add(row["alias"], row["alias"], "query", float(row["weight"]) * 3)
        for row in db.execute("""SELECT query,COUNT(*) uses FROM analytics_events
          WHERE event_type='search' AND query IS NOT NULL
            AND created_at>=CURRENT_TIMESTAMP-INTERVAL '90 days'
          GROUP BY query ORDER BY uses DESC LIMIT 100"""):
            add(row["query"], row["query"], "popular", min(8, float(row["uses"])))
    return [
        item
        for _, item in sorted(
            candidates.values(), key=lambda pair: (pair[0], pair[1]["value"]), reverse=True
        )[: max(1, min(limit, 12))]
    ]


def merchant_detail(merchant_id):
    with connect() as db:
        row = db.execute(
            "SELECT m.*,c.label_fa category_label FROM merchants m JOIN categories c ON c.code=m.category_code WHERE m.id=%s",
            (merchant_id,),
        ).fetchone()
        if not row:
            return None
        merchant = dict(row)
        merchant.pop("avatar_blob", None)
        merchant.pop("avatar_mime_type", None)
        merchant["avatar_url"] = merchant_avatar_url(merchant)
        merchant["posts"] = merchant_posts(db, merchant_id)
        category_rows = {
            item["code"]: dict(item)
            for item in db.execute("SELECT code,parent_code,label_fa FROM categories")
        }
        breadcrumb = []
        code = row["category_code"]
        while code and code in category_rows:
            breadcrumb.insert(0, {"code": code, "label": category_rows[code]["label_fa"]})
            code = category_rows[code]["parent_code"]
        merchant["category_path"] = breadcrumb
        merchant["categories"] = [
            dict(item)
            for item in db.execute(
                """SELECT c.code,c.label_fa label,mc.confidence,mc.source,mc.source_url
            FROM merchant_categories mc JOIN categories c ON c.code=mc.category_code
            WHERE mc.merchant_id=%s ORDER BY mc.confidence DESC,c.level,c.sort_order""",
                (merchant_id,),
            )
        ]
        return merchant


def import_demo_merchant():
    # A real OAuth callback would upsert the authenticated account. The demo must
    # never create a made-up public identity in the directory.
    return {"created": False, "mode": "oauth_demo"}


ANALYTICS_EVENTS = {
    "search",
    "category_view",
    "merchant_click",
    "login_started",
    "login_completed",
    "oauth_started",
    "oauth_completed",
}


def record_event(
    event_type, session_id, query=None, category_code=None, merchant_id=None, result_count=None
):
    if event_type not in ANALYTICS_EVENTS:
        return False
    session_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(session_id or ""))[:80]
    if len(session_id) < 8:
        return False
    query = (query or "").strip()[:160] or None
    try:
        merchant_id = int(merchant_id) if merchant_id is not None else None
        result_count = int(result_count) if result_count is not None else None
    except (TypeError, ValueError):
        return False
    with connect() as db:
        db.execute(
            "INSERT INTO analytics_events(event_type,session_id,query,category_code,merchant_id,result_count) VALUES(%s,%s,%s,%s,%s,%s)",
            (event_type, session_id, query, category_code or None, merchant_id, result_count),
        )
    return True


def admin_mutation_authorized(headers):
    configured = os.environ.get("KAHOO_ADMIN_TOKEN", "")
    if not configured:
        return True
    supplied = headers.get("X-Kahoo-Admin-Token", "")
    return bool(supplied) and hmac.compare_digest(configured, supplied)


def admin_merchants(query="", limit=50, offset=0):
    query = (query or "").strip()[:100]
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))
    params = []
    where = ""
    if query:
        where = "WHERE m.name ILIKE %s OR m.handle ILIKE %s"
        term = f"%{query}%"
        params.extend((term, term))
    with connect() as db:
        total = db.execute(f"SELECT COUNT(*) FROM merchants m {where}", tuple(params)).fetchone()[
            "count"
        ]
        rows = [
            dict(row)
            for row in db.execute(
                f"""
          SELECT m.id,m.name,m.handle,m.category_code,m.city,m.followers_count,
            m.avatar_blob IS NOT NULL has_avatar,COUNT(p.id) post_count
          FROM merchants m LEFT JOIN merchant_posts p ON p.merchant_id=m.id
          {where} GROUP BY m.id ORDER BY m.id DESC LIMIT %s OFFSET %s
        """,
                (*params, limit, offset),
            )
        ]
    for row in rows:
        row["avatar_url"] = f"/api/avatars/{row['id']}" if row.pop("has_avatar") else None
    return {"items": rows, "total": total, "limit": limit, "offset": offset}


def add_or_refresh_merchant(
    identifier, category_code=None, name=None, description=None, city="ایران"
):
    handle = normalize_identifier(identifier)
    try:
        profile = instagram_profile(handle)
    except Exception as error:
        raise ValueError(f"could not read Instagram profile {handle}: {error}") from error
    profile["handle"] = handle
    inferred_code, inferred_description = infer_category(profile)
    category_code = (category_code or inferred_code or "").strip()
    if not category_code:
        raise ValueError("the shop category could not be inferred; choose a category")
    username = handle[1:]
    instagram_url = f"https://www.instagram.com/{username}/"
    name = (name or profile.get("name") or username).strip()
    description = (description or inferred_description or "فروشگاه آنلاین").strip()
    city = (city or "ایران").strip()[:100]
    source = profile.get("source", "instagram_public_embed")
    with connect() as db:
        if not db.execute("SELECT 1 FROM categories WHERE code=%s", (category_code,)).fetchone():
            raise ValueError("unknown GPC category code")
        db.execute("DELETE FROM merchant_exclusions WHERE handle=%s", (handle,))
        existing = db.execute("SELECT id FROM merchants WHERE handle=%s", (handle,)).fetchone()
        if existing:
            merchant_id = existing["id"]
            created = False
            db.execute(
                """UPDATE merchants SET name=%s,description=%s,description_source=%s,
              description_source_url=%s,description_updated_at=CURRENT_TIMESTAMP,
              source_url=%s,category_code=%s,city=%s,avatar_initial=%s,instagram_url=%s,
              biography=%s,biography_source=%s,biography_updated_at=CURRENT_TIMESTAMP,
              followers_count=COALESCE(%s,followers_count),
              following_count=COALESCE(%s,following_count),media_count=COALESCE(%s,media_count),
              metrics_source=%s,metrics_source_url=%s,metrics_updated_at=CURRENT_TIMESTAMP,
              updated_label='داده عمومی' WHERE id=%s""",
                (
                    name,
                    description,
                    source,
                    instagram_url,
                    instagram_url,
                    category_code,
                    city,
                    name[0],
                    instagram_url,
                    profile.get("biography") or "",
                    source,
                    profile.get("followers_count"),
                    profile.get("following_count"),
                    profile.get("media_count"),
                    source,
                    instagram_url,
                    merchant_id,
                ),
            )
        else:
            created = True
            merchant_id = db.execute(
                """INSERT INTO merchants(
              instagram_id,name,handle,description,description_source,
              description_source_url,description_updated_at,source_url,biography,
              biography_source,biography_updated_at,category_code,city,avatar_initial,
              avatar_color,instagram_url,updated_label,verified,followers_count,
              following_count,media_count,metrics_source,metrics_source_url,metrics_updated_at)
              VALUES(%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,%s,%s,%s,CURRENT_TIMESTAMP,%s,%s,%s,%s,%s,
              'داده عمومی',0,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP) RETURNING id""",
                (
                    f"import_{username}",
                    name,
                    handle,
                    description,
                    source,
                    instagram_url,
                    instagram_url,
                    profile.get("biography") or "",
                    source,
                    category_code,
                    city,
                    name[0],
                    "#e3e7e1",
                    instagram_url,
                    profile.get("followers_count"),
                    profile.get("following_count"),
                    profile.get("media_count"),
                    source,
                    instagram_url,
                ),
            ).fetchone()["id"]
        avatar_saved = bool(
            profile.get("avatar_url")
            and cache_merchant_avatar(
                db, merchant_id, name[0], "#e3e7e1", profile["avatar_url"], profile["avatar_url"]
            )
        )
        images_saved = (
            replace_profile_posts(db, merchant_id, name, profile) if profile.get("posts") else 0
        )
        if images_saved:
            db.execute(
                """UPDATE merchants SET instagram_media_sync_version=GREATEST(
              instagram_media_sync_version,%s),instagram_media_synced_at=CURRENT_TIMESTAMP
              WHERE id=%s""",
                (profile.get("media_grouping_version", 1), merchant_id),
            )
        seed_search_metadata(db)
        sync_search_documents(db)
    return {
        "created": created,
        "merchant_id": merchant_id,
        "handle": handle,
        "name": name,
        "category_code": category_code,
        "followers_count": profile.get("followers_count"),
        "avatar_saved": avatar_saved,
        "post_images_saved": images_saved,
    }


def remove_merchant(merchant_id):
    with connect() as db:
        merchant = db.execute(
            "SELECT id,name,handle FROM merchants WHERE id=%s", (merchant_id,)
        ).fetchone()
        if not merchant:
            return None
        db.execute(
            """INSERT INTO merchant_exclusions(handle,reason) VALUES(%s,'admin_removed')
          ON CONFLICT(handle) DO UPDATE SET reason=excluded.reason,created_at=CURRENT_TIMESTAMP""",
            (merchant["handle"],),
        )
        db.execute("DELETE FROM merchants WHERE id=%s", (merchant_id,))
    return dict(merchant)


def admin_metrics(days=30):
    days = days if days in (7, 30, 90) else 30
    since = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d 00:00:00")
    date_keys = [
        (datetime.now() - timedelta(days=offset)).strftime("%Y-%m-%d")
        for offset in range(days - 1, -1, -1)
    ]
    with connect() as db:

        def count(condition):
            return db.execute(
                f"SELECT COUNT(*) FROM analytics_events WHERE created_at>=%s AND {condition}",
                (since,),
            ).fetchone()["count"]

        searches = count("event_type='search'")
        clicks = count("event_type='merchant_click'")
        zero_searches = count("event_type='search' AND result_count=0")
        visitors = db.execute(
            "SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at>=%s", (since,)
        ).fetchone()["count"]
        searched_sessions = db.execute(
            "SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at>=%s AND event_type='search'",
            (since,),
        ).fetchone()["count"]
        clicked_sessions = db.execute(
            "SELECT COUNT(DISTINCT session_id) FROM analytics_events WHERE created_at>=%s AND event_type='merchant_click'",
            (since,),
        ).fetchone()["count"]
        daily_rows = {
            row["event_day"]: dict(row)
            for row in db.execute(
                """
          SELECT to_char(created_at,'YYYY-MM-DD') AS event_day,
            COUNT(*) FILTER (WHERE event_type='search') searches,
            COUNT(*) FILTER (WHERE event_type='merchant_click') clicks,
            COUNT(DISTINCT session_id) visitors,
            COUNT(*) FILTER (WHERE event_type='search' AND result_count=0) zero_results
          FROM analytics_events WHERE created_at>=%s GROUP BY 1 ORDER BY 1
        """,
                (since,),
            )
        }
        daily = [
            {"date": day, "searches": 0, "clicks": 0, "visitors": 0, "zero_results": 0}
            | daily_rows.get(day, {})
            for day in date_keys
        ]
        top_queries = [
            dict(row)
            for row in db.execute(
                """
          SELECT query,COUNT(*) searches,ROUND(AVG(result_count),1)::double precision avg_results,
            COUNT(*) FILTER (WHERE result_count=0) zero_results
          FROM analytics_events WHERE created_at>=%s AND event_type='search' AND query IS NOT NULL
          GROUP BY query ORDER BY searches DESC LIMIT 10
        """,
                (since,),
            )
        ]
        missed_queries = [
            dict(row)
            for row in db.execute(
                """
          SELECT query,COUNT(*) searches FROM analytics_events
          WHERE created_at>=%s AND event_type='search' AND result_count=0 AND query IS NOT NULL
          GROUP BY query ORDER BY searches DESC LIMIT 8
        """,
                (since,),
            )
        ]
        top_merchants = [
            dict(row)
            for row in db.execute(
                """
          SELECT m.id,m.name,m.handle,COUNT(e.id) clicks FROM analytics_events e
          JOIN merchants m ON m.id=e.merchant_id
          WHERE e.created_at>=%s AND e.event_type='merchant_click'
          GROUP BY m.id ORDER BY clicks DESC,m.id DESC LIMIT 8
        """,
                (since,),
            )
        ]
        top_categories = [
            dict(row)
            for row in db.execute(
                """
          SELECT c.label_fa label,COUNT(e.id) views FROM analytics_events e
          JOIN categories c ON c.code=e.category_code
          WHERE e.created_at>=%s AND e.event_type='category_view'
          GROUP BY c.code ORDER BY views DESC LIMIT 8
        """,
                (since,),
            )
        ]
        catalog = dict(
            db.execute("""
          SELECT (SELECT COUNT(*) FROM merchants) merchants,
            (SELECT COUNT(DISTINCT category_code) FROM merchants) used_categories,
            (SELECT COUNT(*) FROM merchant_posts) posts,
            (SELECT COUNT(*) FROM merchants WHERE avatar_blob IS NOT NULL) avatars,
            (SELECT COUNT(*) FROM merchants WHERE description!='') descriptions
        """).fetchone()
        )
        oauth_started = count("event_type='oauth_started'")
        oauth_completed = count("event_type='oauth_completed'")
    return {
        "period_days": days,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "kpis": {
            "searches": searches,
            "visitors": visitors,
            "clicks": clicks,
            "zero_rate": round(zero_searches / searches * 100, 1) if searches else 0,
            "search_to_click": round(clicked_sessions / searched_sessions * 100, 1)
            if searched_sessions
            else 0,
        },
        "catalog": catalog,
        "daily": daily,
        "top_queries": top_queries,
        "missed_queries": missed_queries,
        "top_merchants": top_merchants,
        "top_categories": top_categories,
        "funnel": {
            "visitors": visitors,
            "searched": searched_sessions,
            "clicked": clicked_sessions,
            "oauth_started": oauth_started,
            "oauth_completed": oauth_completed,
        },
    }


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, data, content_type, status=200, cache_control=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, payload, status=200):
        body = json.dumps(
            payload,
            ensure_ascii=False,
            default=lambda value: (
                value.isoformat()
                if isinstance(value, (date, datetime))
                else float(value)
                if isinstance(value, Decimal)
                else str(value)
            ),
        ).encode()
        self.send_bytes(body, "application/json; charset=utf-8", status)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/categories":
            return self.send_json(category_tree())
        if parsed.path == "/api/search/suggestions":
            args = parse_qs(parsed.query)
            return self.send_json(search_suggestions(args.get("q", [""])[0]))
        if parsed.path == "/api/merchants":
            args = parse_qs(parsed.query)
            category = args.get("category", [None])[0]
            query = args.get("q", [""])[0]
            result = merchants(category, query)
            session_id = self.headers.get("X-Kahoo-Session")
            if query:
                record_event(
                    "search",
                    session_id,
                    query=query,
                    category_code=category,
                    result_count=len(result),
                )
            elif category:
                record_event(
                    "category_view", session_id, category_code=category, result_count=len(result)
                )
            return self.send_json(result)
        if parsed.path.startswith("/api/merchants/"):
            try:
                merchant_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                return self.send_error(404)
            result = merchant_detail(merchant_id)
            return self.send_json(result) if result else self.send_error(404)
        if parsed.path == "/api/admin/metrics":
            args = parse_qs(parsed.query)
            try:
                days = int(args.get("days", [30])[0])
            except ValueError:
                days = 30
            return self.send_json(admin_metrics(days))
        if parsed.path == "/api/admin/merchants":
            args = parse_qs(parsed.query)
            try:
                limit = int(args.get("limit", [50])[0])
                offset = int(args.get("offset", [0])[0])
            except ValueError:
                return self.send_json({"error": "invalid_pagination"}, 400)
            return self.send_json(admin_merchants(args.get("q", [""])[0], limit, offset))
        if parsed.path.startswith("/api/media/"):
            try:
                post_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                return self.send_error(404)
            with connect() as db:
                media = db.execute(
                    "SELECT image_blob,mime_type FROM merchant_posts WHERE id=%s", (post_id,)
                ).fetchone()
            if not media or media["image_blob"] is None:
                return self.send_error(404)
            return self.send_bytes(
                media["image_blob"],
                media["mime_type"] or "application/octet-stream",
                cache_control="public, max-age=86400",
            )
        if parsed.path.startswith("/api/avatars/"):
            try:
                merchant_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                return self.send_error(404)
            with connect() as db:
                avatar = db.execute(
                    "SELECT avatar_blob,avatar_mime_type FROM merchants WHERE id=%s", (merchant_id,)
                ).fetchone()
            if not avatar or avatar["avatar_blob"] is None:
                return self.send_error(404)
            return self.send_bytes(
                avatar["avatar_blob"],
                avatar["avatar_mime_type"] or "application/octet-stream",
                cache_control="public, max-age=86400",
            )
        path = PUBLIC_ROOT / ("index.html" if parsed.path == "/" else parsed.path.lstrip("/"))
        if not path.is_file() or PUBLIC_ROOT not in path.resolve().parents:
            return self.send_error(404)
        self.send_bytes(
            path.read_bytes(), mimetypes.guess_type(path)[0] or "application/octet-stream"
        )

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_json({"error": "invalid_content_length"}, 400)
        if length < 0:
            return self.send_json({"error": "invalid_content_length"}, 400)
        if length > 1_048_576:
            return self.send_json({"error": "request_too_large"}, 413)
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.send_json({"error": "invalid_json"}, 400)
        if not isinstance(payload, dict):
            return self.send_json({"error": "invalid_json"}, 400)
        if self.path == "/api/analytics/event":
            session_id = self.headers.get("X-Kahoo-Session") or payload.get("session_id")
            saved = record_event(
                payload.get("event_type"),
                session_id,
                payload.get("query"),
                payload.get("category_code"),
                payload.get("merchant_id"),
                payload.get("result_count"),
            )
            return self.send_json({"saved": saved}, 201 if saved else 400)
        if self.path == "/api/login/request":
            return self.send_json(
                {"challenge_id": str(uuid.uuid4()), "phone": payload.get("phone")}
            )
        if self.path == "/api/login/verify":
            if len(str(payload.get("code", ""))) != 5:
                return self.send_json({"error": "invalid_code"}, 400)
            return self.send_json(
                {"user": {"phone": payload.get("phone"), "display_name": "حساب من"}}
            )
        if self.path == "/api/merchants/import-demo":
            return self.send_json(import_demo_merchant(), 201)
        if self.path == "/api/admin/merchants":
            if not admin_mutation_authorized(self.headers):
                return self.send_json(
                    {"error": "unauthorized", "message": "کلید مدیریت نادرست است."}, 401
                )
            try:
                result = add_or_refresh_merchant(
                    payload.get("identifier"),
                    payload.get("category_code"),
                    payload.get("name"),
                    payload.get("description"),
                    payload.get("city", "ایران"),
                )
            except ValueError as error:
                return self.send_json(
                    {"error": "merchant_import_failed", "message": str(error)}, 400
                )
            except Exception:
                logger.exception("Merchant import failed")
                return self.send_json(
                    {"error": "merchant_import_failed", "message": "ذخیره فروشگاه ممکن نشد."}, 500
                )
            return self.send_json(result, 201 if result["created"] else 200)
        return self.send_error(404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/admin/merchants/"):
            return self.send_error(404)
        if not admin_mutation_authorized(self.headers):
            return self.send_json(
                {"error": "unauthorized", "message": "کلید مدیریت نادرست است."}, 401
            )
        try:
            merchant_id = int(parsed.path.rsplit("/", 1)[1])
        except ValueError:
            return self.send_json({"error": "invalid_merchant_id"}, 400)
        removed = remove_merchant(merchant_id)
        return (
            self.send_json({"removed": removed})
            if removed
            else self.send_json({"error": "not_found"}, 404)
        )
