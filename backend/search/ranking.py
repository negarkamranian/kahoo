import math
from difflib import SequenceMatcher

from backend.search.normalization import normalize_search, query_tokens, token_variants


def query_coverage(tokens, *texts):
    """Fraction of meaningful query tokens matched by any searchable field."""
    if not tokens:
        return 0.0
    return sum(
        any(term_match_strength(token, text) > 0 for text in texts) for token in tokens
    ) / len(tokens)


def phrase_proximity_bonus(phrase, text):
    """Reward exact phrases and compact ordered matches without overmatching."""
    phrase = normalize_search(phrase)
    text = normalize_search(text)
    if not phrase or not text:
        return 0.0
    if f" {phrase} " in f" {text} ":
        return 1.0
    tokens = query_tokens(phrase)
    words = text.split()
    if len(tokens) < 2:
        return 0.0
    positions = []
    start = -1
    for token in tokens:
        matches = [
            index
            for index, word in enumerate(words)
            if index > start and term_match_strength(token, word) >= 0.7
        ]
        if not matches:
            return 0.0
        start = matches[0]
        positions.append(start)
    span = positions[-1] - positions[0] + 1
    return max(0.0, 0.8 - 0.1 * max(0, span - len(tokens)))


def term_match_strength(term, text):
    """Return 0..1 for exact, prefix, or conservative typo-tolerant matching."""
    term = normalize_search(term)
    text = normalize_search(text)
    if not term or not text:
        return 0.0
    if f" {term} " in f" {text} ":
        return 1.0
    if " " in term:
        return 0.0
    words = text.split()
    variants = token_variants(term)
    if any(variant in words for variant in variants):
        return 1.0
    if len(term) >= 3 and any(
        word.startswith(term) or term.startswith(word)
        for word in words
        if min(len(word), len(term)) >= 3
    ):
        return 0.72
    if len(term) < 4:
        return 0.0
    similarity = max(
        (
            SequenceMatcher(None, term, word).ratio()
            for word in words
            if abs(len(word) - len(term)) <= 2
        ),
        default=0.0,
    )
    return 0.55 if similarity >= 0.78 else 0.0


def reciprocal_rank_fusion(*rankings, k=60):
    """Fuse score dictionaries without comparing their incompatible scales."""
    fused = {}
    for ranking in rankings:
        ordered = sorted(ranking, key=ranking.get, reverse=True)
        for rank, merchant_id in enumerate(ordered, 1):
            fused[merchant_id] = fused.get(merchant_id, 0.0) + 1 / (k + rank)
    return fused


def discounted_cumulative_gain(relevances, limit=10):
    return sum(
        (2**relevance - 1) / math.log2(rank + 2)
        for rank, relevance in enumerate(relevances[:limit])
    )


def ndcg_at_k(relevances, ideal_relevances=None, limit=10):
    ideal = sorted(ideal_relevances or relevances, reverse=True)
    denominator = discounted_cumulative_gain(ideal, limit)
    return discounted_cumulative_gain(relevances, limit) / denominator if denominator else 0.0


def merchant_quality_score(merchant, clicks=0):
    """Small, bounded tie-breaker for browse/recommendation quality."""
    followers = max(0, int(merchant.get("followers_count") or 0))
    media = max(0, int(merchant.get("media_count") or 0))
    return (
        min(math.log1p(followers) / 3.0, 4.8)
        + min(math.log1p(media) / 6.0, 1.6)
        + min(math.log1p(max(0, clicks)) / 4.0, 1.0)
        + (0.35 if merchant.get("avatar_source_url") else 0)
        + (0.25 if merchant.get("biography") else 0)
        + (0.2 if merchant.get("verified") else 0)
    )


def diversify_results(items, penalty=0.85):
    """Greedy re-rank that prevents one catalog segment monopolizing browse."""
    remaining = list(items)
    output = []
    segment_counts = {}
    while remaining:
        best = max(
            remaining,
            key=lambda item: (
                item.get("search_score", 0)
                - penalty * segment_counts.get(str(item.get("category_code", ""))[:2], 0)
            ),
        )
        remaining.remove(best)
        output.append(best)
        segment = str(best.get("category_code", ""))[:2]
        segment_counts[segment] = segment_counts.get(segment, 0) + 1
    return output
