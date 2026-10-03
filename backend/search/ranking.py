import math
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from backend.models.merchants import Merchant
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
    if token_variants(term).intersection(words):
        return EXACT_TERM_STRENGTH
    if prefix_term_match(term, words):
        return PREFIX_TERM_STRENGTH
    return fuzzy_term_strength(term, words)


def prefix_term_match(term, words):
    return len(term) >= MIN_PREFIX_LENGTH and any(
        word.startswith(term) or term.startswith(word)
        for word in words
        if min(len(word), len(term)) >= MIN_PREFIX_LENGTH
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


@dataclass
class TextMatch:
    score: float = 0
    phrase_bonus: float = 0
    coverage: float = 0
    matched_tokens: int = 0
    fields: set[str] = field(default_factory=set)
    fuzzy: bool = False


def searchable_fields(merchant, category_labels):
    fields = [
        ("name", f"{merchant.name} {merchant.handle}", 14, 20),
        ("description", merchant.description, 7, 13),
        ("biography", merchant.biography, 5, 9),
        ("category", " ".join(category_labels), 9, 14),
        ("city", merchant.city, 3, 0),
    ]
    fields = [(name, normalize_search(text), weight, bonus) for name, text, weight, bonus in fields]
    return fields


def score_token(match, token, fields, stored_terms):
    token_score = 0
    for name, text, weight, _ in fields:
        strength = term_match_strength(token, text)
        token_score += weight * strength
        if strength >= STRONG_TERM_THRESHOLD:
            match.fields.add(name)
        match.fuzzy |= 0 < strength < STRONG_TERM_THRESHOLD
    metadata = max(
        (weight * term_match_strength(token, term) for term, weight in stored_terms), default=0
    )
    if metadata >= STRONG_TERM_THRESHOLD:
        match.fields.add("metadata")
    token_score += METADATA_WEIGHT * metadata
    match.score += token_score
    match.matched_tokens += token_score > 0


def content_phrase_bonus(phrase, fields):
    return sum(
        bonus * term_match_strength(phrase, text) for _, text, _, bonus in fields if bonus
    ) + PROXIMITY_WEIGHT * max(
        phrase_proximity_bonus(phrase, text) for _, text, _, bonus in fields if bonus
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
    match.coverage = query_coverage(
        tokens, *(text for _, text, _, _ in fields), " ".join(term for term, _ in stored_terms)
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
