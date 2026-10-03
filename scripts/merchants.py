from backend.database import connect
from backend.instagram import instagram_profile, normalize_identifier
from backend.search.indexing import sync_search_documents
from backend.search.metadata import sync_search_metadata
from backend.server.media import cache_merchant_avatar, replace_profile_posts


def add_or_refresh_merchant(
    identifier, category_code=None, name=None, description=None, city="ایران"
):
    handle = normalize_identifier(identifier)
    for field, value in (
        ("category", category_code),
        ("name", name),
        ("description", description),
        ("city", city),
    ):
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{field} must be text")
    with connect() as db:
        existing = db.execute(
            "SELECT id,category_code FROM merchants WHERE handle=%s", (handle,)
        ).fetchone()
        category_code = (category_code or "").strip() or (
            existing["category_code"] if existing else None
        )
        if not category_code:
            raise ValueError("choose a GPC category for a new merchant (--category)")
        category = db.execute(
            "SELECT code,label_fa FROM categories WHERE code=%s", (category_code,)
        ).fetchone()
        if not category:
            raise ValueError("unknown GPC category code")
    try:
        profile = instagram_profile(handle)
    except (OSError, ValueError) as error:
        raise ValueError(f"could not read Instagram profile {handle}: {error}") from error
    username = handle[1:]
    instagram_url = f"https://www.instagram.com/{username}/"
    name = (name or profile.get("name") or username).strip() or username
    description = (description or category["label_fa"]).strip()
    city = (city or "ایران").strip()[:100]
    source = profile.get("source", "instagram_public_embed")
    with connect() as db:
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
        sync_search_metadata(db)
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


def add(args):
    return add_or_refresh_merchant(
        args.identifier, args.category, args.name, args.description, args.city
    )


def import_file(args):
    identifiers = list(
        dict.fromkeys(
            normalize_identifier(value) for value in args.source.read_text(encoding="utf-8").split()
        )
    )
    results = []
    for identifier in identifiers:
        try:
            results.append(
                add_or_refresh_merchant(identifier, category_code=args.category, city=args.city)
            )
        except (ValueError, OSError) as error:
            results.append({"handle": identifier, "error": str(error)})
    return {"results": results, "failed": sum("error" in item for item in results)}


def list_merchants(args):
    from backend.server.merchants import admin_merchants

    return admin_merchants(args.query, args.limit, args.offset)


def remove(args):
    from backend.server.merchants import remove_merchant

    merchant = remove_merchant(args.merchant_id)
    if not merchant:
        raise ValueError("merchant not found")
    return {"removed": merchant}
