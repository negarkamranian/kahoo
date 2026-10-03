#!/usr/bin/env python3
"""Retrieve and store missing merchant profile pictures and Instagram posts."""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import connect, run_migrations
from backend.server import (
    ensure_gallery_images,
    instagram_media_backfill_status,
    refresh_instagram_profiles,
)


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve and save missing merchant avatars and post images."
    )
    parser.add_argument(
        "handles",
        nargs="*",
        help="optional Instagram handles; checks every merchant when omitted",
    )
    parser.add_argument(
        "--minimum-post-images",
        type=int,
        default=3,
        metavar="COUNT",
        help="consider a gallery incomplete below this count (default: 3)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="maximum incomplete merchants to process; 0 means all",
    )
    args = parser.parse_args()
    if args.minimum_post_images < 0:
        parser.error("--minimum-post-images must be zero or greater")
    if args.limit < 0:
        parser.error("--limit must be zero or greater")

    run_migrations()
    with connect() as database:
        existing_cache = ensure_gallery_images(database)

    before = instagram_media_backfill_status(args.minimum_post_images, args.handles)
    print(f"Found {len(before)} merchants with missing media.", flush=True)

    def show_result(result):
        if not result["updated"]:
            print(f"  {result['handle']}: FAILED - {result['error']}", flush=True)
            return
        parts = []
        if result["needed_avatar"]:
            parts.append("avatar saved" if result["avatar_saved"] else "avatar missing")
        if result["needed_posts"]:
            parts.append(f"{result['images_saved']} post images saved")
        print(f"  {result['handle']}: {', '.join(parts)}", flush=True)

    profiles = refresh_instagram_profiles(
        args.handles,
        on_start=lambda handle: print(f"  Reading {handle}...", flush=True),
        on_result=show_result,
        only_missing=True,
        minimum_images=args.minimum_post_images,
        limit=args.limit,
    )
    after = instagram_media_backfill_status(args.minimum_post_images, args.handles)
    report = {
        "incomplete_before": len(before),
        "profiles_attempted": len(profiles),
        "profiles_updated": sum(item["updated"] for item in profiles),
        "profiles_failed": sum(not item["updated"] for item in profiles),
        "profile_images_saved": sum(bool(item.get("avatar_saved")) for item in profiles),
        "post_images_saved": sum(item.get("images_saved", 0) for item in profiles),
        "existing_post_cache": existing_cache,
        "incomplete_after": len(after),
        "remaining": after,
        "profiles": profiles,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
