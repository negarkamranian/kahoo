from backend.database import connect
from backend.models.media import SyncBatch
from backend.services.media import ensure_gallery_images
from backend.services.profiles import (
    instagram_media_backfill_status,
    refresh_instagram_avatars,
    refresh_instagram_profiles,
)


def status(args):
    return instagram_media_backfill_status(args.minimum_post_images, args.handles)


def cache(args):
    with connect() as db:
        return ensure_gallery_images(db, args.handles)


def sync(args):
    if args.avatars_only:
        profiles = refresh_instagram_avatars(
            args.handles,
            only_missing=args.only_missing,
            limit=args.limit,
        )
    else:
        profiles = refresh_instagram_profiles(
            args.handles,
            only_missing=args.only_missing,
            minimum_images=args.minimum_post_images,
            limit=args.limit,
        )
    return SyncBatch(
        attempted=len(profiles),
        failed=0,
        profiles=profiles,
    )
