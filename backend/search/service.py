"""Compose merchant retrieval, relevance ranking and media presentation."""

import math

from backend.database import connect
from backend.models.merchants import Merchant
from backend.models.search import SearchContext, SearchEvidence
from backend.search.data import (
    load_categories,
    load_category_assignments,
    load_click_counts,
    load_query_click_counts,
    load_search_terms,
)
from backend.search.embeddings import semantic_merchant_scores
from backend.search.normalization import normalize_search, query_tokens
from backend.search.ranking import (
    diversify_results,
    match_content,
    merchant_quality_score,
    reciprocal_rank_fusion,
)
from backend.search.retrieval import lexical_merchant_matches
from backend.services.merchants import merchant_avatar_url, merchant_posts

MAX_QUERY_LENGTH = 120
FUSION_WEIGHT = 300
COVERAGE_WEIGHT = 8
QUALITY_WEIGHT = 0.15
CLICK_WEIGHT = 0.7
MAX_CLICK_BOOST = 2.0

# Priority follows the strongest user-facing explanation, independent of scores.
MATCH_REASONS = (
    ({"name"}, "نام فروشگاه"),
    ({"post"}, "محصول یا پست مرتبط"),
    ({"category"}, "دسته‌بندی مرتبط"),
    ({"description", "metadata"}, "محصولات مرتبط"),
    ({"biography"}, "بیوی فروشگاه"),
    ({"city"}, "موقعیت فروشگاه"),
    ({"semantic"}, "نتیجه معنایی نزدیک"),
)
DEFAULT_MATCH_REASON = "عبارت مشابه"


def load_search_context(db, query):
    phrase = normalize_search(query)[:MAX_QUERY_LENGTH]
    categories = load_categories(db)
    assignments = load_category_assignments(db)
    terms = load_search_terms(db)
    lexical = lexical_merchant_matches(db, phrase) if phrase else {}
    semantic = semantic_merchant_scores(db, phrase) if phrase else {}
    return SearchContext(
        phrase=phrase,
        tokens=query_tokens(phrase),
        categories=categories,
        assignments=assignments,
        terms=terms,
        lexical=lexical,
        semantic=semantic,
        fused=reciprocal_rank_fusion(
            {key: match.score for key, match in lexical.items()}, semantic
        ),
        clicks=load_click_counts(db),
        query_clicks=load_query_click_counts(db, query) if phrase else {},
    )


def merchant_rows(db, category):
    sql = "SELECT m.* FROM merchants m"
    params = []
    if category:
        sql += """ WHERE EXISTS (SELECT 1 FROM merchant_categories mc WHERE mc.merchant_id=m.id
          AND mc.category_code IN (WITH RECURSIVE branch(code) AS (SELECT %s UNION ALL
          SELECT c.code FROM categories c JOIN branch b ON c.parent_code=b.code) SELECT code FROM branch))"""
        params.append(category)
    return db.execute(sql + " ORDER BY m.id DESC", params)


def category_labels(merchant, context):
    labels = []
    codes = context.assignments.get(merchant.id, [merchant.category_code])
    for code in codes:
        while code and code in context.categories:
            category = context.categories[code]
            labels.extend((category["label_fa"], category["label_en"]))
            code = category["parent_code"]
    return labels


def merchant_evidence(merchant, context):
    text = match_content(
        merchant,
        category_labels(merchant, context),
        context.terms.get(merchant.id, []),
        context.phrase,
        context.tokens,
    )
    return SearchEvidence(
        text, context.lexical.get(merchant.id), context.semantic.get(merchant.id, 0)
    )


def relevant_match(evidence, tokens):
    if not tokens:
        return False
    if evidence.has_semantic_match or evidence.has_document_match:
        return True
    text = evidence.text
    if text.score + text.phrase_bonus == 0:
        return False
    required_matches = max(2, (len(tokens) + 1) // 2)
    return len(tokens) == 1 or text.matched_tokens >= required_matches


def relevance_score(merchant_id, evidence, context, quality):
    text = evidence.text
    behavior = min(
        MAX_CLICK_BOOST, math.log1p(context.query_clicks.get(merchant_id, 0)) * CLICK_WEIGHT
    )
    return (
        text.score
        + text.phrase_bonus
        + context.fused.get(merchant_id, 0) * FUSION_WEIGHT
        + text.coverage * COVERAGE_WEIGHT
        + behavior
        + quality * QUALITY_WEIGHT
    )


def match_reason(evidence):
    signals = set(evidence.text.fields)
    if evidence.has_post:
        signals.add("post")
    if evidence.has_semantic_match:
        signals.add("semantic")
    return next(
        (reason for fields, reason in MATCH_REASONS if fields & signals), DEFAULT_MATCH_REASON
    )


def match_quality(evidence):
    if evidence.text.fields:
        return "exact"
    if evidence.text.fuzzy:
        return "near"
    return "semantic" if evidence.has_semantic_match else "exact"


def explain_match(merchant, evidence):
    merchant.match_reason = match_reason(evidence)
    merchant.match_quality = match_quality(evidence)
    merchant.match_coverage = round(evidence.text.coverage, 2)
    if evidence.has_post:
        merchant.matched_post_id = evidence.lexical.entity_id


def attach_media(db, merchant, row):
    if row["avatar_blob"] is not None:
        merchant.avatar_url = merchant_avatar_url(merchant.id, merchant.avatar_updated_at)
    merchant.posts = merchant_posts(db, merchant.id)
    if merchant.matched_post_id:
        merchant.posts.sort(key=lambda post: post.post_id != merchant.matched_post_id)


def ranked_merchants(db, rows, context, query):
    results = []
    for row in rows:
        merchant = Merchant.model_validate(row)
        score = merchant_quality_score(merchant, context.clicks.get(merchant.id, 0))
        if query:
            evidence = merchant_evidence(merchant, context)
            if not relevant_match(evidence, context.tokens):
                continue
            score = relevance_score(merchant.id, evidence, context, score)
            if score == 0:
                continue
            explain_match(merchant, evidence)
        attach_media(db, merchant, row)
        merchant.search_score = round(score, 2)
        results.append(merchant)
    return sorted(results, key=lambda merchant: (merchant.search_score, merchant.id), reverse=True)


def merchants(category=None, query="") -> list[Merchant]:
    with connect() as db:
        context = load_search_context(db, query)
        ranked = ranked_merchants(db, merchant_rows(db, category), context, query)
    return diversify_results(ranked) if not query and not category else ranked
