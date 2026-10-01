#!/usr/bin/env python3
"""Add or refresh one Instagram shop by its public handle or profile URL."""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.database import connect, run_category_seed, run_migrations
from backend.search import sync_search_documents
from backend.server import (
    DATA_ROOT,
    cache_merchant_avatar,
    instagram_profile,
    replace_profile_posts,
    seed_search_metadata,
)


CATEGORY_RULES = (
    ("10000000", "خوراک، لوازم و محصولات مراقبت حیوانات خانگی", ("حیوان خانگی", "سگ", "گربه", "پت شاپ", "pet shop", "petcare")),
    ("53161000", "لوازم آرایشی، مراقبت پوست و مو و محصولات زیبایی", ("آرایش", "میکاپ", "پوست", "مراقبت مو", "عطر", "ادکلن", "beauty", "cosmetic", "perfume")),
    ("66010100", "لوازم جانبی موبایل، قاب، کاور و اکسسوری دیجیتال", ("قاب", "کاور", "گلس", "case", "cover", "mobile accessory")),
    ("66010300", "موبایل، تبلت و محصولات دیجیتال", ("موبایل", "گوشی", "تبلت", "mobile", "phone")),
    ("63010300", "کفش، بوت، صندل و پاپوش", ("کفش", "بوت", "صندل", "shoe", "boot", "sneaker")),
    ("64010100", "طلا، جواهرات و زیورآلات", ("طلا", "جواهر", "زیور", "gold", "jewel")),
    ("60010200", "کتاب و محصولات فرهنگی", ("کتاب", "book")),
    ("62060100", "لوازم تحریر و نوشت‌افزار", ("تحریر", "نوشت افزار", "stationery")),
    ("86010400", "اسباب‌بازی، بازی فکری و محصولات کودک", ("اسباب بازی", "بازی فکری", "toy", "lego")),
    ("73040000", "لوازم خانه، آشپزخانه و دکوراسیون", ("خانه", "آشپزخانه", "دکور", "home", "kitchen")),
    ("50230100", "مواد غذایی، نوشیدنی و محصولات سوپرمارکتی", ("مواد غذایی", "سوپرمارکت", "خوراکی", "food", "market")),
    ("67010000", "پوشاک و اکسسوری مد", ("پوشاک", "لباس", "مانتو", "مزون", "شومیز", "fashion", "clothing", "wear", "label")),
)


def normalize_identifier(identifier):
    value = identifier.strip().lower()
    if "://" in value:
        parsed = urlparse(value)
        if parsed.netloc not in {"instagram.com", "www.instagram.com"}:
            raise ValueError("the URL must be an instagram.com profile URL")
        value = parsed.path.strip("/").split("/", 1)[0]
    value = value.lstrip("@").strip("/")
    if not re.fullmatch(r"[a-z0-9._]{1,30}", value):
        raise ValueError("use an Instagram username, @username, or profile URL")
    return f"@{value}"


def infer_category(profile):
    captions = " ".join(post.get("caption") or "" for post in profile.get("posts", []))
    text = " ".join((profile.get("handle") or "", profile.get("name") or "", profile.get("biography") or "", captions)).lower().replace("‌", " ")
    scored = []
    for order, (code, description, keywords) in enumerate(CATEGORY_RULES):
        score = sum(text.count(keyword) for keyword in keywords)
        if score:
            scored.append((score, -order, code, description))
    if not scored:
        return None, None
    _, _, code, description = max(scored)
    return code, description


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
