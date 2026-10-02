#!/usr/bin/env python3
"""Add or refresh one Instagram shop by its public handle or profile URL."""

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import connect, run_category_seed, run_migrations
from backend.merchant_import import infer_category, normalize_identifier
from backend.search import sync_search_documents
from backend.server import (
    DATA_ROOT,
    cache_merchant_avatar,
    instagram_profile,
    replace_profile_posts,
    seed_search_metadata,
)


def parser():
    command = argparse.ArgumentParser(
        description="Add or refresh a shop from its public Instagram account."
    )
    command.add_argument("identifier", help="username, @username, or Instagram profile URL")
    command.add_argument("--category", help="GPC category code; inferred when omitted")
    command.add_argument("--name", help="merchant display name; Instagram name is used by default")
    command.add_argument("--description", help="merchant description; generated from the inferred category by default")
    command.add_argument("--city", default="ایران", help="merchant city (default: ایران)")
    return command


def main():
    args = parser().parse_args()
    try:
        handle = normalize_identifier(args.identifier)
    except ValueError as error:
        parser().error(str(error))

    print(f"Reading public Instagram profile {handle}...", flush=True)
    try:
        profile = instagram_profile(handle)
    except Exception as error:
        parser().error(f"could not read {handle}: {error}")

    profile["handle"] = handle
    inferred_code, inferred_description = infer_category(profile)
    category_code = args.category or inferred_code
    if not category_code:
        parser().error(
            "the shop category could not be inferred; rerun with --category GPC_CODE"
        )

    username = handle[1:]
    instagram_url = f"https://www.instagram.com/{username}/"
    name = (args.name or profile.get("name") or username).strip()
    description = (args.description or inferred_description or "فروشگاه آنلاین").strip()
    source = profile.get("source", "instagram_public_embed")

    print("Applying migrations and saving the merchant, avatar, and posts...", flush=True)
    run_migrations()
    run_category_seed(DATA_ROOT / "categories.sql")
    with connect() as database:
        database.execute("DELETE FROM merchant_exclusions WHERE handle=?", (handle,))
        if not database.execute("SELECT 1 FROM categories WHERE code=?", (category_code,)).fetchone():
            parser().error(f"unknown GPC category code: {category_code}")
        existing = database.execute(
            "SELECT id FROM merchants WHERE handle=?", (handle,)
        ).fetchone()
        if existing:
            merchant_id = existing["id"]
            created = False
            database.execute(
                """UPDATE merchants SET name=?,description=?,description_source=?,
                  description_source_url=?,description_updated_at=CURRENT_TIMESTAMP,
                  source_url=?,category_code=?,city=?,avatar_initial=?,instagram_url=?,
                  biography=?,biography_source=?,biography_updated_at=CURRENT_TIMESTAMP,
                  followers_count=COALESCE(?,followers_count),
                  following_count=COALESCE(?,following_count),
                  media_count=COALESCE(?,media_count),metrics_source=?,
                  metrics_source_url=?,metrics_updated_at=CURRENT_TIMESTAMP,
                  updated_label='داده عمومی' WHERE id=?""",
                (name, description, source, instagram_url, instagram_url, category_code,
                 args.city, name[0], instagram_url, profile.get("biography") or "", source,
                 profile.get("followers_count"), profile.get("following_count"),
                 profile.get("media_count"), source, instagram_url, merchant_id),
            )
        else:
            created = True
            merchant_id = database.execute(
                """INSERT INTO merchants(
                  instagram_id,name,handle,description,description_source,
                  description_source_url,description_updated_at,source_url,biography,
                  biography_source,biography_updated_at,category_code,city,avatar_initial,
                  avatar_color,instagram_url,updated_label,verified,followers_count,
                  following_count,media_count,metrics_source,metrics_source_url,
                  metrics_updated_at) VALUES(?,?,?,?,?,?,CURRENT_TIMESTAMP,?,?,?,
                  CURRENT_TIMESTAMP,?,?,?,?,?,'داده عمومی',0,?,?,?,?,?,CURRENT_TIMESTAMP)
                  RETURNING id""",
                (f"import_{username}", name, handle, description, source, instagram_url,
                 instagram_url, profile.get("biography") or "", source, category_code,
                 args.city, name[0], "#e3e7e1", instagram_url,
                 profile.get("followers_count"), profile.get("following_count"),
                 profile.get("media_count"), source, instagram_url),
            ).fetchone()["id"]

        avatar_saved = bool(
            profile.get("avatar_url")
            and cache_merchant_avatar(database, merchant_id, name[0], "#e3e7e1",
                                      profile["avatar_url"], profile["avatar_url"])
        )
        images_saved = replace_profile_posts(database, merchant_id, name, profile)
        if images_saved:
            database.execute(
                """UPDATE merchants SET instagram_media_sync_version=GREATEST(
                  instagram_media_sync_version,?),instagram_media_synced_at=CURRENT_TIMESTAMP
                  WHERE id=?""",
                (profile.get("media_grouping_version", 1), merchant_id),
            )
        seed_search_metadata(database)
        sync_search_documents(database)

    print(json.dumps({
        "created": created,
        "merchant_id": merchant_id,
        "handle": handle,
        "name": name,
        "category_code": category_code,
        "followers_count": profile.get("followers_count"),
        "avatar_saved": avatar_saved,
        "post_images_saved": images_saved,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
