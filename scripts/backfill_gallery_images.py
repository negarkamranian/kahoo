#!/usr/bin/env python3
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import connect, run_migrations
from backend.search import sync_search_documents
from backend.server import ensure_gallery_images, refresh_instagram_profiles


def main():
    run_migrations()
    with connect() as database:
        generated = list(
            database.execute(
                """DELETE FROM merchant_posts
               WHERE image_url LIKE 'kahoo://gallery-placeholder/%'
                  OR caption='تصویر عمومی فروشگاه؛ منبع در نشانی تصویر ثبت شده است'
               RETURNING id"""
            )
        )
    print("Refreshing shop posts and carousel collections...", flush=True)

    def show_profile(result):
        if result["updated"]:
            print(
                f"  {result['handle']}: {result['posts_found']} posts, "
                f"{result['images_saved']} images saved",
                flush=True,
            )
        else:
            print(f"  {result['handle']}: FAILED - {result['error']}", flush=True)

    profiles = refresh_instagram_profiles(on_result=show_profile)
    with connect() as database:
        cache = ensure_gallery_images(database)
        sync_search_documents(database)
    updated = [item for item in profiles if item["updated"]]
    result = {
        "removed_generated_images": len(generated),
        "profiles_attempted": len(profiles),
        "profiles_updated": len(updated),
        "profiles_failed": len(profiles) - len(updated),
        "images_saved": sum(item.get("images_saved", 0) for item in updated),
        "cache": cache,
        "profiles": profiles,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
