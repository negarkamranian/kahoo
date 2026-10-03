import logging
import math

import psycopg

from backend.database import connect
from backend.search.embeddings import semantic_merchant_scores
from backend.search.normalization import normalize_search, query_tokens
from backend.search.ranking import (
    diversify_results,
    merchant_quality_score,
    phrase_proximity_bonus,
    query_coverage,
    reciprocal_rank_fusion,
    term_match_strength,
)
from backend.search.retrieval import lexical_merchant_matches
from backend.server.merchants import merchant_avatar_url, merchant_posts

logger = logging.getLogger(__name__)


def merchants(category=None, query=""):
    params = []
    where = []
    if category:
        where.append("""EXISTS (SELECT 1 FROM merchant_categories mc WHERE mc.merchant_id=m.id
          AND mc.category_code IN (WITH RECURSIVE branch(code) AS (SELECT %s UNION ALL
          SELECT c.code FROM categories c JOIN branch b ON c.parent_code=b.code) SELECT code FROM branch))""")
        params.append(category)
    sql = (
        "SELECT m.* FROM merchants m"
        + (" WHERE " + " AND ".join(where) if where else "")
        + " ORDER BY m.id DESC"
    )
    with connect() as db:
        category_rows = {
            row["code"]: dict(row)
            for row in db.execute("SELECT code,parent_code,label_fa,label_en FROM categories")
        }
        categories_by_merchant = {}
        for item in db.execute("SELECT merchant_id,category_code FROM merchant_categories"):
            categories_by_merchant.setdefault(item["merchant_id"], []).append(item["category_code"])
        terms_by_merchant = {}
        for item in db.execute(
            "SELECT merchant_id,normalized_term,weight,confidence FROM merchant_search_terms"
        ):
            terms_by_merchant.setdefault(item["merchant_id"], []).append(
                (item["normalized_term"], item["weight"] * item["confidence"])
            )
        phrase = normalize_search(query)[:120]
        tokens = query_tokens(phrase)
        lexical_matches = lexical_merchant_matches(db, phrase) if phrase else {}
        lexical_document_scores = {
            merchant_id: match["score"] for merchant_id, match in lexical_matches.items()
        }
        try:
            with db.transaction():
                semantic_scores = semantic_merchant_scores(db, phrase) if phrase else {}
        except (OSError, ValueError, psycopg.Error):
            logger.exception("Semantic search failed")
            semantic_scores = {}
        fused_scores = reciprocal_rank_fusion(lexical_document_scores, semantic_scores)
        click_counts = {
            row["merchant_id"]: row["clicks"]
            for row in db.execute(
                """SELECT merchant_id,COUNT(*) clicks FROM analytics_events
             WHERE event_type='merchant_click' AND merchant_id IS NOT NULL
               AND created_at>=CURRENT_TIMESTAMP-INTERVAL '30 days'
             GROUP BY merchant_id"""
            )
        }
        query_click_counts = {}
        if phrase:
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
        result = []
        for row in db.execute(sql, params):
            merchant = dict(row)
            match_fields = set()
            fuzzy_match = False
            quality_score = merchant_quality_score(merchant, click_counts.get(row["id"], 0))
            if query:
                category_labels = []
                for category_code in categories_by_merchant.get(row["id"], [row["category_code"]]):
                    code = category_code
                    while code and code in category_rows:
                        category_labels.extend(
                            (category_rows[code]["label_fa"], category_rows[code]["label_en"])
                        )
                        code = category_rows[code]["parent_code"]
                identity = normalize_search(f"{row['name']} {row['handle']}")
                city = normalize_search(row["city"])
                description = normalize_search(row["description"])
                biography = normalize_search(row["biography"])
                category_text = normalize_search(" ".join(category_labels))
                stored_terms = terms_by_merchant.get(row["id"], [])

                def term_score(term):
                    nonlocal fuzzy_match
                    strengths = {
                        "name": term_match_strength(term, identity),
                        "description": term_match_strength(term, description),
                        "biography": term_match_strength(term, biography),
                        "category": term_match_strength(term, category_text),
                        "city": term_match_strength(term, city),
                    }
                    metadata = max(
                        (
                            weight * term_match_strength(term, stored)
                            for stored, weight in stored_terms
                        ),
                        default=0,
                    )
                    match_fields.update(
                        field for field, strength in strengths.items() if strength >= 0.7
                    )
                    if metadata >= 0.7:
                        match_fields.add("metadata")
                    fuzzy_match = fuzzy_match or any(
                        0 < strength < 0.7 for strength in strengths.values()
                    )
                    return (
                        14 * strengths["name"]
                        + 7 * strengths["description"]
                        + 5 * strengths["biography"]
                        + 9 * strengths["category"]
                        + 3 * strengths["city"]
                        + 6 * metadata
                    )

                token_scores = [term_score(token) for token in tokens]
                exact_score = sum(token_scores)
                semantic_score = semantic_scores.get(row["id"], 0)
                document_score = lexical_document_scores.get(row["id"], 0)
                proximity = max(
                    phrase_proximity_bonus(phrase, identity),
                    phrase_proximity_bonus(phrase, category_text),
                    phrase_proximity_bonus(phrase, description),
                    phrase_proximity_bonus(phrase, biography),
                )
                phrase_bonus = (
                    20 * term_match_strength(phrase, identity)
                    + 13 * term_match_strength(phrase, description)
                    + 9 * term_match_strength(phrase, biography)
                    + 14 * term_match_strength(phrase, category_text)
                    + 10 * proximity
                )
                coverage = query_coverage(
                    tokens,
                    identity,
                    category_text,
                    description,
                    biography,
                    city,
                    " ".join(term for term, _ in stored_terms),
                )
                behavior_boost = min(2.0, math.log1p(query_click_counts.get(row["id"], 0)) * 0.7)
                score = (
                    exact_score
                    + phrase_bonus
                    + fused_scores.get(row["id"], 0) * 300
                    + coverage * 8
                    + behavior_boost
                    + quality_score * 0.15
                )
                required_matches = max(2, (len(tokens) + 1) // 2)
                weak_lexical = (
                    len(tokens) > 1 and sum(value > 0 for value in token_scores) < required_matches
                )
                no_strong_signal = (
                    exact_score + phrase_bonus == 0
                    and semantic_score < 0.55
                    and document_score < 0.25
                )
                if (
                    not tokens
                    or score == 0
                    or no_strong_signal
                    or (weak_lexical and semantic_score < 0.55 and document_score < 0.25)
                ):
                    continue
                if "name" in match_fields:
                    reason = "نام فروشگاه"
                elif lexical_matches.get(row["id"], {}).get("entity_type") == "post":
                    reason = "محصول یا پست مرتبط"
                elif "category" in match_fields:
                    reason = "دسته‌بندی مرتبط"
                elif "description" in match_fields or "metadata" in match_fields:
                    reason = "محصولات مرتبط"
                elif "biography" in match_fields:
                    reason = "بیوی فروشگاه"
                elif "city" in match_fields:
                    reason = "موقعیت فروشگاه"
                elif semantic_score >= 0.55:
                    reason = "نتیجه معنایی نزدیک"
                else:
                    reason = "عبارت مشابه"
                merchant["match_reason"] = reason
                merchant["match_quality"] = (
                    "near"
                    if fuzzy_match and not match_fields
                    else "semantic"
                    if not match_fields and semantic_score >= 0.55
                    else "exact"
                )
                merchant["match_coverage"] = round(coverage, 2)
                lexical_match = lexical_matches.get(row["id"])
                if lexical_match and lexical_match["entity_type"] == "post":
                    merchant["matched_post_id"] = lexical_match["entity_id"]
            else:
                score = quality_score
            merchant.pop("avatar_blob", None)
            merchant.pop("avatar_mime_type", None)
            merchant["avatar_url"] = merchant_avatar_url(merchant)
            merchant["posts"] = merchant_posts(db, row["id"])
            if merchant.get("matched_post_id"):
                merchant["posts"].sort(
                    key=lambda post: post["post_id"] != merchant["matched_post_id"]
                )
            merchant["search_score"] = round(score, 2)
            result.append(merchant)
        ranked = sorted(
            result, key=lambda merchant: (merchant["search_score"], merchant["id"]), reverse=True
        )
        return diversify_results(ranked) if not query and not category else ranked
