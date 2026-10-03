"""Load the independent inputs used by merchant ranking."""


def load_categories(db):
    category_rows = {
        row["code"]: dict(row)
        for row in db.execute("SELECT code,parent_code,label_fa,label_en FROM categories")
    }
    return category_rows


def load_category_assignments(db):
    categories_by_merchant = {}
    for item in db.execute("SELECT merchant_id,category_code FROM merchant_categories"):
        categories_by_merchant.setdefault(item["merchant_id"], []).append(item["category_code"])
    return categories_by_merchant


def load_search_terms(db):
    terms_by_merchant = {}
    for item in db.execute(
        "SELECT merchant_id,normalized_term,weight,confidence FROM merchant_search_terms"
    ):
        terms_by_merchant.setdefault(item["merchant_id"], []).append(
            (item["normalized_term"], item["weight"] * item["confidence"])
        )
    return terms_by_merchant


def load_click_counts(db):
    click_counts = {
        row["merchant_id"]: row["clicks"]
        for row in db.execute(
            """SELECT merchant_id,COUNT(*) clicks FROM analytics_events
         WHERE event_type='merchant_click' AND merchant_id IS NOT NULL
           AND created_at>=CURRENT_TIMESTAMP-INTERVAL '30 days'
         GROUP BY merchant_id"""
        )
    }
    return click_counts


def load_query_click_counts(db, query):
    query_click_counts = {
        row["merchant_id"]: row["clicks"]
        for row in db.execute(
            """SELECT merchant_id,COUNT(*) clicks FROM analytics_events
         WHERE event_type='merchant_click' AND merchant_id IS NOT NULL
           AND created_at>=CURRENT_TIMESTAMP-INTERVAL '90 days'
           AND LOWER(query)=LOWER(%s) GROUP BY merchant_id""",
            (query,),
        )
    }
    return query_click_counts
