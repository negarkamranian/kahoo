#!/usr/bin/env python3
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import connect, run_category_seed, run_migrations
from backend.search import sync_search_documents
from backend.server import (
    DATA_ROOT,
    catalog_profiles_missing_posts,
    refresh_instagram_avatars,
    refresh_instagram_profiles,
    seed_public_catalog,
    seed_search_metadata,
)


def main():
    print("Applying database migrations and merchant catalog...",flush=True)
    run_migrations()
    run_category_seed(DATA_ROOT / "categories.sql")
    with connect() as database:
        result = seed_public_catalog(database)
        seed_search_metadata(database)
        sync_search_documents(database)
        result["total"] = database.execute(
            "SELECT COUNT(*) FROM merchants"
        ).fetchone()[0]
    incomplete_profiles = catalog_profiles_missing_posts()
    print(
        f"Synchronizing posts for {len(incomplete_profiles)} incomplete shops...",
        flush=True,
    )

    def show_profile(result):
        if result["updated"]:
            print(
                f"  {result['handle']}: {result['images_saved']} post images, "
                f"avatar={'saved' if result['avatar_saved'] else 'failed'}",
                flush=True,
            )
        else:
            print(f"  {result['handle']}: FAILED - {result['error']}", flush=True)

    synced_profiles = (
        refresh_instagram_profiles(
            incomplete_profiles,
            on_start=lambda handle: print(f"  Reading {handle}...", flush=True),
            on_result=show_profile,
        )
        if incomplete_profiles
        else []
    )
    print("Repairing remaining profile pictures...",flush=True)

    def show_avatar(result):
        status="saved" if result["updated"] else f"FAILED - {result['error']}"
        print(f"  {result['handle']}: {status}",flush=True)

    missing_avatars = refresh_instagram_avatars(on_result=show_avatar)
    result["profile_media_sync"] = {
        "requested_handles": incomplete_profiles,
        "profiles": synced_profiles,
        "still_missing_posts": catalog_profiles_missing_posts(),
    }
    result["missing_profile_images"] = missing_avatars
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
