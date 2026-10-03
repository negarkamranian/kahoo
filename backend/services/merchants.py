import re
from datetime import datetime

from backend.database import connect
from backend.instagram import instagram_profile, instagram_shortcode, normalize_identifier
from backend.search.indexing import sync_search_documents
from backend.search.metadata import sync_search_metadata
from backend.services.media import cache_merchant_avatar, replace_profile_posts


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
