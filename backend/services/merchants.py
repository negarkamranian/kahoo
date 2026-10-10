from datetime import datetime
from itertools import groupby

from backend.database import connect
from backend.instagram.service import instagram_profile
from backend.instagram.urls import profile_url
from backend.models.categories import CategoryLink
from backend.models.media import MediaAsset, PostCollection
from backend.models.merchants import (
    AdminMerchant,
    AdminMerchantPage,
    AdminMerchantQuery,
    ImportResult,
    Merchant,
    MerchantImport,
    MerchantSummary,
)
from backend.search.indexing import sync_search_index
from backend.services.media import cache_merchant_avatar, replace_profile_posts


def merchant_posts(db, merchant_id: int) -> list[PostCollection]:
    rows = list(
        db.execute(
            "SELECT id,image_url,permalink,position,collection_key,media_position,caption FROM merchant_posts "
            "WHERE merchant_id=%s AND image_blob IS NOT NULL ORDER BY position,media_position",
            (merchant_id,),
        )
    )
    return [
        post_collection(key, list(items), position)
        for position, (key, items) in enumerate(
            groupby(rows, key=lambda row: row["collection_key"]), 1
        )
    ]


def post_collection(collection_key, collection_rows, position):
    first = collection_rows[0]
    unique_images = {}
    for row in collection_rows:
        unique_images.setdefault(row["image_url"], row)
    collection = [
        MediaAsset(media_url=f"/api/media/{row['id']}", position=position)
        for position, row in enumerate(unique_images.values(), 1)
    ]

    return PostCollection(
        post_id=first["id"],
        key=collection_key,
        permalink=first["permalink"],
        caption=first["caption"],
        position=position,
        media=collection,
    )


def merchant_avatar_url(merchant_id: int, updated_at: datetime | None) -> str:
    if updated_at is None:
        return f"/api/avatars/{merchant_id}"
    version = int(updated_at.timestamp() * 1_000_000)
    return f"/api/avatars/{merchant_id}?v={version}"


def merchant_detail(merchant_id: int) -> Merchant | None:
    with connect() as db:
        row = db.execute(
            "SELECT m.*,c.label_fa category_label FROM merchants m JOIN categories c ON c.code=m.category_code WHERE m.id=%s",
            (merchant_id,),
        ).fetchone()
        if not row:
            return None
        merchant = Merchant.model_validate(row)
        if row["avatar_blob"] is not None:
            merchant.avatar_url = merchant_avatar_url(merchant.id, merchant.avatar_updated_at)
        merchant.posts = merchant_posts(db, merchant_id)
        category_rows = {
            item["code"]: dict(item)
            for item in db.execute("SELECT code,parent_code,label_fa FROM categories")
        }
        merchant.category_path = category_breadcrumb(row["category_code"], category_rows)
        merchant.categories = [
            CategoryLink.model_validate(item)
            for item in db.execute(
                """SELECT c.code,c.label_fa label,mc.confidence,mc.source,mc.source_url
            FROM merchant_categories mc JOIN categories c ON c.code=mc.category_code
            WHERE mc.merchant_id=%s ORDER BY mc.confidence DESC,c.level,c.sort_order""",
                (merchant_id,),
            )
        ]
        return merchant


def admin_merchant_item(row):
    row["avatar_url"] = merchant_avatar_url(row["id"], None) if row.pop("has_avatar") else None
    return AdminMerchant.model_validate(row)


def admin_merchants(request: AdminMerchantQuery) -> AdminMerchantPage:
    query = request.query.strip()
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
                (*params, request.limit, request.offset),
            )
        ]
    return AdminMerchantPage(
        items=[admin_merchant_item(row) for row in rows],
        total=total,
        limit=request.limit,
        offset=request.offset,
    )


def remove_merchant(merchant_id: int) -> MerchantSummary | None:
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
    return MerchantSummary.model_validate(merchant)


def import_category(request):
    category_code = request.category_code
    with connect() as db:
        existing = db.execute(
            "SELECT id,category_code FROM merchants WHERE handle=%s", (request.identifier,)
        ).fetchone()
        if category_code is None and existing is not None:
            category_code = existing["category_code"]
        if not category_code:
            raise ValueError("choose a GPC category for a new merchant (--category)")
        category = db.execute(
            "SELECT code FROM categories WHERE code=%s", (category_code,)
        ).fetchone()
        if not category:
            raise ValueError("unknown GPC category code")
    return category_code


def update_imported_merchant(db, merchant_id, request, profile, category_code):
    instagram_url = profile_url(request.identifier)
    db.execute(
        """UPDATE merchants SET name=%s,description=%s,description_source=%s,
      description_source_url=%s,description_updated_at=CURRENT_TIMESTAMP,
      source_url=%s,category_code=%s,city=%s,instagram_url=%s,
      biography=%s,biography_source=%s,biography_updated_at=CURRENT_TIMESTAMP,
      followers_count=COALESCE(%s,followers_count),
      following_count=COALESCE(%s,following_count),media_count=COALESCE(%s,media_count),
      metrics_source=%s,metrics_source_url=%s,metrics_updated_at=CURRENT_TIMESTAMP,
      updated_label='داده عمومی' WHERE id=%s""",
        (
            profile.name,
            profile.biography,
            profile.source,
            instagram_url,
            instagram_url,
            category_code,
            request.city,
            instagram_url,
            profile.biography,
            profile.source,
            profile.followers_count,
            profile.following_count,
            profile.media_count,
            profile.source,
            instagram_url,
            merchant_id,
        ),
    )


def create_imported_merchant(db, request, profile, category_code):
    instagram_url = profile_url(request.identifier)
    return db.execute(
        """INSERT INTO merchants(
      instagram_id,name,handle,description,description_source,
      description_source_url,description_updated_at,source_url,biography,
      biography_source,biography_updated_at,category_code,city,
      instagram_url,updated_label,verified,followers_count,
      following_count,media_count,metrics_source,metrics_source_url,metrics_updated_at)
      VALUES(%s,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP,%s,%s,%s,CURRENT_TIMESTAMP,%s,%s,%s,
      'داده عمومی',0,%s,%s,%s,%s,%s,CURRENT_TIMESTAMP) RETURNING id""",
        (
            f"import_{request.identifier[1:]}",
            profile.name,
            request.identifier,
            profile.biography,
            profile.source,
            instagram_url,
            instagram_url,
            profile.biography,
            profile.source,
            category_code,
            request.city,
            instagram_url,
            profile.followers_count,
            profile.following_count,
            profile.media_count,
            profile.source,
            instagram_url,
        ),
    ).fetchone()["id"]


def add_or_refresh_merchant(request: MerchantImport) -> ImportResult:
    category_code = import_category(request)
    profile = instagram_profile(request.identifier)
    with connect() as db:
        db.execute("DELETE FROM merchant_exclusions WHERE handle=%s", (request.identifier,))
        existing = db.execute(
            "SELECT id FROM merchants WHERE handle=%s", (request.identifier,)
        ).fetchone()
        if existing:
            merchant_id = existing["id"]
            update_imported_merchant(db, merchant_id, request, profile, category_code)
        else:
            merchant_id = create_imported_merchant(db, request, profile, category_code)
        avatar_saved = save_imported_avatar(db, merchant_id, profile)
        images_saved = replace_profile_posts(db, merchant_id, profile)
        sync_search_index(db)
    return ImportResult(
        created=not bool(existing),
        merchant_id=merchant_id,
        handle=request.identifier,
        name=profile.name,
        category_code=category_code,
        followers_count=profile.followers_count,
        avatar_saved=avatar_saved,
        post_images_saved=images_saved,
    )


def save_imported_avatar(db, merchant_id, profile):
    if not profile.avatar_url:
        return False
    cache_merchant_avatar(db, merchant_id, profile.avatar_url, profile.avatar_url)
    return True


def category_breadcrumb(category_code, category_rows):
    breadcrumb = []
    code = category_code
    while code and code in category_rows:
        breadcrumb.insert(0, CategoryLink(code=code, label=category_rows[code]["label_fa"]))
        code = category_rows[code]["parent_code"]
    return breadcrumb
