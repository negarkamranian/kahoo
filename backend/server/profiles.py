from backend.database import connect
from backend.instagram import INSTAGRAM_MEDIA_SYNC_VERSION, instagram_profile, normalize_identifier
from backend.search.indexing import sync_search_documents
from backend.search.metadata import sync_search_metadata
from backend.server.media import cache_merchant_avatar, replace_profile_posts


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
        sync_search_metadata(db)
        sync_search_documents(db)
    return results


def refresh_instagram_avatars(handles=None, on_result=None, only_missing=False, limit=0):
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
        if only_missing and has_remote_avatar:
            continue
        if limit and len(results) >= limit:
            break
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
