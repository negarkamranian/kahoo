import math
from difflib import SequenceMatcher
from functools import lru_cache

from backend.models.merchants import Merchant
from backend.models.search import SearchField, TextMatch
from backend.search.normalization import normalize_search, query_tokens, token_variants

# Conservative token matching: short prefixes and loose typos overmatch Persian words.
EXACT_TERM_STRENGTH = 1.0
PREFIX_TERM_STRENGTH = 0.72
FUZZY_TERM_STRENGTH = 0.55
MIN_PREFIX_LENGTH = 3
MIN_FUZZY_LENGTH = 4
MAX_TYPO_LENGTH_DIFFERENCE = 2
MIN_TYPO_SIMILARITY = 0.78
STRONG_TERM_THRESHOLD = 0.7
METADATA_WEIGHT = 6
PROXIMITY_WEIGHT = 10


def query_coverage(tokens, *texts):
    """Fraction of meaningful query tokens matched by any searchable field."""
    if not tokens:
        return 0.0
    return sum(
        any(term_match_strength(token, text) > 0 for text in texts) for token in tokens
    ) / len(tokens)


def compact_query_match(tokens, text):
    """Require concepts to occur together, rather than in unrelated product lists."""
    if len(tokens) < 2:
        return True
    words = normalize_search(text).split()
    events = [
        (position, token)
        for position, word in enumerate(words)
        for token in tokens
        if term_match_strength(token, word) >= FUZZY_TERM_STRENGTH
    ]
    counts = {}
    start = 0
    for position, token in events:
        counts[token] = counts.get(token, 0) + 1
        while position - events[start][0] >= max(6, len(tokens) + 3):
            previous = events[start][1]
            counts[previous] -= 1
            if counts[previous] == 0:
                del counts[previous]
            start += 1
        if len(counts) == len(tokens):
            return True
    return False


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
            if index > start and term_match_strength(token, word) >= STRONG_TERM_THRESHOLD
        ]
        if not matches:
            return 0.0
        start = matches[0]
        positions.append(start)
    span = positions[-1] - positions[0] + 1
    return max(0.0, 0.8 - 0.1 * max(0, span - len(tokens)))


@lru_cache(maxsize=32768)
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
    if any(token_variants(term) & token_variants(word) for word in words):
        return EXACT_TERM_STRENGTH
    if prefix_term_match(term, words):
        return PREFIX_TERM_STRENGTH
    return fuzzy_term_strength(term, words)


def prefix_term_match(term, words):
    return len(term) >= MIN_PREFIX_LENGTH and any(
        word.startswith(term) for word in words if min(len(word), len(term)) >= MIN_PREFIX_LENGTH
    )


def fuzzy_term_strength(term, words):
    if len(term) < MIN_FUZZY_LENGTH:
        return 0.0
    similarity = max(
        (
            SequenceMatcher(None, term, word).ratio()
            for word in words
            if abs(len(word) - len(term)) <= MAX_TYPO_LENGTH_DIFFERENCE
        ),
        default=0.0,
    )
    return FUZZY_TERM_STRENGTH if similarity >= MIN_TYPO_SIMILARITY else 0.0


def searchable_fields(merchant, category_labels):
    fields = [
        SearchField(
            name="name",
            text=f"{merchant.name} {merchant.handle}",
            token_weight=14,
            phrase_weight=20,
        ),
        SearchField(
            name="description", text=merchant.description, token_weight=7, phrase_weight=13
        ),
        SearchField(name="biography", text=merchant.biography, token_weight=5, phrase_weight=9),
        SearchField(
            name="category", text=" ".join(category_labels), token_weight=4, phrase_weight=6
        ),
        SearchField(name="city", text=merchant.city, token_weight=3, phrase_weight=0),
    ]
    return [
        SearchField(
            name=item.name,
            text=normalize_search(item.text),
            token_weight=item.token_weight,
            phrase_weight=item.phrase_weight,
        )
        for item in fields
    ]


def score_token(match, token, fields, stored_terms):
    # A concept contributes once: repeating it across generated text is not evidence.
    scores = []
    for content in fields:
        strength = term_match_strength(token, content.text)
        scores.append(content.token_weight * strength)
        if strength >= STRONG_TERM_THRESHOLD:
            match.fields.add(content.name)
        match.fuzzy |= 0 < strength < STRONG_TERM_THRESHOLD
    metadata = max(
        (weight * term_match_strength(token, term) for term, weight in stored_terms), default=0
    )
    if metadata >= STRONG_TERM_THRESHOLD:
        match.fields.add("metadata")
    scores.append(METADATA_WEIGHT * metadata)
    token_score = max(scores)
    match.score += token_score
    match.matched_tokens += token_score > 0


def content_phrase_bonus(phrase, fields):
    return sum(
        content.phrase_weight * term_match_strength(phrase, content.text)
        for content in fields
        if content.phrase_weight
    ) + PROXIMITY_WEIGHT * max(
        phrase_proximity_bonus(phrase, content.text) for content in fields if content.phrase_weight
    )


def match_content(
    merchant: Merchant,
    category_labels: list[str],
    stored_terms: list[tuple[str, float]],
    phrase: str,
    tokens: list[str],
) -> TextMatch:
    """Score searchable fields without mutating the merchant or querying the database."""
    fields = searchable_fields(merchant, category_labels)
    match = TextMatch()
    for token in tokens:
        score_token(match, token, fields, stored_terms)
    match.phrase_bonus = content_phrase_bonus(phrase, fields)
    match.coverage = match.matched_tokens / len(tokens) if tokens else 0
    product_tokens = [token for token in tokens if term_match_strength(token, merchant.city) == 0]
    match.coherent = any(
        compact_query_match(product_tokens, text)
        for text in [
            *(field.text for field in fields if field.name != "city"),
            *(term for term, _ in stored_terms),
        ]
    )
    return match


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
    if ideal_relevances is None:
        ideal_relevances = relevances
    ideal = sorted(ideal_relevances, reverse=True)
    denominator = discounted_cumulative_gain(ideal, limit)
    if denominator == 0:
        return 0.0
    return discounted_cumulative_gain(relevances, limit) / denominator


def merchant_quality_score(merchant: Merchant, clicks: int = 0) -> float:
    """Small, bounded tie-breaker for browse/recommendation quality."""
    followers = max(0, (merchant.followers_count or 0))
    media = max(0, (merchant.media_count or 0))
    score = (
        min(math.log1p(followers) / 3.0, 4.8)
        + min(math.log1p(media) / 6.0, 1.6)
        + min(math.log1p(max(0, clicks)) / 4.0, 1.0)
    )
    if merchant.avatar_source_url:
        score += 0.35
    if merchant.biography:
        score += 0.25
    if merchant.verified:
        score += 0.2
    return score


def diversify_results(items: list[Merchant], penalty: float = 0.85) -> list[Merchant]:
    """Greedy re-rank that prevents one catalog segment monopolizing browse."""
    remaining = list(items)
    output = []
    segment_counts = {}
    while remaining:
        best = max(
            remaining,
            key=lambda item: (
                item.search_score - penalty * segment_counts.get(item.category_code[:2], 0)
            ),
        )
        remaining.remove(best)
        output.append(best)
        segment = best.category_code[:2]
        segment_counts[segment] = segment_counts.get(segment, 0) + 1
    return output
