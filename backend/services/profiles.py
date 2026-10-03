from collections.abc import Callable
from functools import partial

from backend.database import connect
from backend.instagram import instagram_profile
from backend.instagram_urls import profile_url
from backend.models.media import (
    MINIMUM_POST_IMAGES,
    InstagramProfile,
    MediaBackfillStatus,
    MerchantMedia,
    SyncResult,
)
from backend.search.indexing import sync_search_index
from backend.services.media import cache_merchant_avatar, replace_profile_posts


def merchant_media_rows() -> list[MerchantMedia]:
    with connect() as db:
        return [
            MerchantMedia.model_validate(row)
            for row in db.execute("""SELECT m.id,m.handle,m.name,m.description_source,m.avatar_blob,m.avatar_mime_type,
          m.avatar_source_url,m.instagram_media_sync_version,
          COUNT(p.id) FILTER (WHERE p.image_blob IS NOT NULL) cached_images
          FROM merchants m LEFT JOIN merchant_posts p ON p.merchant_id=m.id
          GROUP BY m.id ORDER BY m.id""")
        ]


def instagram_media_backfill_status(
    minimum_images=MINIMUM_POST_IMAGES, handles=None
) -> list[MediaBackfillStatus]:
    requested = set(handles or [])
    return [
        MediaBackfillStatus(
            id=merchant.id,
            handle=merchant.handle,
            missing_avatar=merchant.needs_avatar,
            missing_posts=merchant.needs_posts(minimum_images),
            cached_images=merchant.cached_images,
            media_sync_version=merchant.instagram_media_sync_version,
        )
        for merchant in merchant_media_rows()
        if (not requested or merchant.handle in requested) and merchant.needs_media(minimum_images)
    ]


def _save_profile(
    db, merchant: MerchantMedia, profile: InstagramProfile, only_missing: bool, minimum_images: int
) -> SyncResult:
    save_profile_details(db, merchant, profile)
    avatar_saved = False
    if profile.avatar_url and (not only_missing or merchant.needs_avatar):
        cache_merchant_avatar(
            db,
            merchant.id,
            profile.avatar_url,
            profile.avatar_url,
        )
        avatar_saved = True
    posts_saved = 0
    if profile.posts and (not only_missing or merchant.needs_posts(minimum_images)):
        posts_saved = replace_profile_posts(db, merchant.id, profile)
    sync_search_index(db)
    return SyncResult(
        handle=merchant.handle,
        updated=True,
        source=profile.source,
        posts_found=len(profile.posts),
        images_saved=posts_saved,
        avatar_saved=avatar_saved,
        has_biography=bool(profile.biography),
        needed_avatar=merchant.needs_avatar,
        needed_posts=merchant.needs_posts(minimum_images),
    )


def _save_avatar(db, merchant: MerchantMedia, profile: InstagramProfile) -> SyncResult:
    if not profile.avatar_url:
        return SyncResult(handle=merchant.handle, updated=False)
    mime_type = cache_merchant_avatar(
        db,
        merchant.id,
        profile.avatar_url,
        profile.avatar_url,
    )
    return SyncResult(handle=merchant.handle, updated=True, mime_type=mime_type)


def _refresh(
    handles: list[str] | None,
    only_missing: bool,
    limit: int | None,
    on_result: Callable[[SyncResult], None] | None,
    needs_refresh: Callable[[MerchantMedia], bool],
    save_profile: Callable,
    on_start: Callable[[str], None] | None = None,
) -> list[SyncResult]:
    requested = set(handles or [])
    selected = [
        merchant
        for merchant in merchant_media_rows()
        if (not requested or merchant.handle in requested)
        and (not only_missing or needs_refresh(merchant))
    ]
    if limit and limit > 0:
        selected = selected[:limit]
    results = []
    for merchant in selected:
        if on_start:
            on_start(merchant.handle)
        profile = instagram_profile(merchant.handle)
        with connect() as db:
            result = save_profile(db, merchant, profile)
        results.append(result)
        if on_result:
            on_result(result)
    return results


def refresh_instagram_profiles(
    handles=None,
    on_result=None,
    on_start=None,
    only_missing=False,
    minimum_images=MINIMUM_POST_IMAGES,
    limit=None,
) -> list[SyncResult]:
    return _refresh(
        handles,
        only_missing,
        limit,
        on_result,
        needs_refresh=lambda merchant: merchant.needs_media(minimum_images),
        save_profile=partial(
            _save_profile, only_missing=only_missing, minimum_images=minimum_images
        ),
        on_start=on_start,
    )


def refresh_instagram_avatars(
    handles=None, on_result=None, only_missing=False, limit=0
) -> list[SyncResult]:
    return _refresh(
        handles,
        only_missing,
        limit,
        on_result,
        needs_refresh=lambda merchant: merchant.needs_avatar,
        save_profile=_save_avatar,
    )


def save_profile_details(db, merchant, profile):
    db.execute(
        """UPDATE merchants SET name=%s,
          biography=%s,biography_source=%s,
          biography_updated_at=CURRENT_TIMESTAMP,followers_count=COALESCE(%s,followers_count),
          following_count=COALESCE(%s,following_count),media_count=COALESCE(%s,media_count),
          metrics_source=%s,metrics_source_url=%s,metrics_updated_at=CURRENT_TIMESTAMP WHERE id=%s""",
        (
            profile.name,
            profile.biography,
            profile.source,
            profile.followers_count,
            profile.following_count,
            profile.media_count,
            profile.source,
            profile_url(merchant.handle),
            merchant.id,
        ),
    )
