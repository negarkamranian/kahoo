"""Collect, score and deduplicate autocomplete suggestions."""

from enum import IntEnum

from backend.database import connect
from backend.models.search import SearchSuggestion
from backend.search.normalization import normalize_search
from backend.search.ranking import term_match_strength

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 80
MAX_SUGGESTIONS = 12
MERCHANT_NAME_BOOST = 8
MERCHANT_HANDLE_BOOST = 7
CATEGORY_BOOST = 5
MAX_POPULARITY_BOOST = 8


class MatchScore(IntEnum):
    EXACT = 100
    PHRASE_PREFIX = 85
    WORD_PREFIX = 75
    SUBSTRING = 65
    TERM_MATCH = 40


def exact_match(phrase, text):
    return text == phrase


def phrase_prefix(phrase, text):
    return text.startswith(phrase)


def word_prefix(phrase, text):
    return any(word.startswith(phrase) for word in text.split())


def substring_match(phrase, text):
    return phrase in text


# First matching rule wins; specific matches rank above broader matches.
MATCH_RULES = (
    (exact_match, MatchScore.EXACT),
    (phrase_prefix, MatchScore.PHRASE_PREFIX),
    (word_prefix, MatchScore.WORD_PREFIX),
    (substring_match, MatchScore.SUBSTRING),
)


def suggestion_score(phrase, normalized):
    if not normalized:
        return 0
    for matches, score in MATCH_RULES:
        if matches(phrase, normalized):
            return float(score)
    return MatchScore.TERM_MATCH * term_match_strength(phrase, normalized)


def merchant_suggestions(db):
    for row in db.execute("SELECT name,handle FROM merchants"):
        label = f"{row['name']} · {row['handle']}"
        yield SearchSuggestion(value=row["name"], label=label, type="merchant"), MERCHANT_NAME_BOOST
        yield (
            SearchSuggestion(value=row["handle"].lstrip("@"), label=label, type="merchant"),
            MERCHANT_HANDLE_BOOST,
        )


def category_suggestions(db, phrase):
    pattern = f"%{phrase}%"
    rows = db.execute(
        """SELECT label_fa FROM categories
          WHERE level>=2 AND (label_fa ILIKE %s OR label_en ILIKE %s)
          ORDER BY level,sort_order LIMIT 100""",
        (pattern, pattern),
    )
    for row in rows:
        yield (
            SearchSuggestion(value=row["label_fa"], label=row["label_fa"], type="category"),
            CATEGORY_BOOST,
        )


def term_suggestions(db, phrase):
    rows = db.execute(
        """SELECT term,MAX(weight) weight FROM merchant_search_terms
           WHERE normalized_term ILIKE %s GROUP BY term ORDER BY weight DESC LIMIT 100""",
        (f"{phrase}%",),
    )
    for row in rows:
        yield (
            SearchSuggestion(value=row["term"], label=row["term"], type="query"),
            float(row["weight"]),
        )


def popular_suggestions(db):
    rows = db.execute("""SELECT query,COUNT(*) uses FROM analytics_events
          WHERE event_type='search' AND query IS NOT NULL AND result_count>0
            AND created_at>=CURRENT_TIMESTAMP-INTERVAL '90 days'
          GROUP BY query ORDER BY uses DESC LIMIT 100""")
    for row in rows:
        yield (
            SearchSuggestion(value=row["query"], label=row["query"], type="popular"),
            min(MAX_POPULARITY_BOOST, float(row["uses"])),
        )


def collect_suggestions(db, phrase):
    yield from merchant_suggestions(db)
    yield from category_suggestions(db, phrase)
    yield from term_suggestions(db, phrase)
    yield from popular_suggestions(db)


def rank_suggestions(phrase, suggestions, limit):
    candidates = {}
    for item, boost in suggestions:
        normalized = normalize_search(item.value)
        match = suggestion_score(phrase, normalized)
        if not match:
            continue
        score = match + boost
        previous = candidates.get(normalized)
        if previous is None or score > previous[0]:
            candidates[normalized] = (score, item)
    ranked = sorted(candidates.values(), key=lambda pair: (pair[0], pair[1].value), reverse=True)
    return [item for _, item in ranked[: max(1, min(limit, MAX_SUGGESTIONS))]]


def search_suggestions(query: str, limit: int = 8) -> list[SearchSuggestion]:
    phrase = normalize_search(query)[:MAX_QUERY_LENGTH]
    if len(phrase) < MIN_QUERY_LENGTH:
        return []
    with connect() as db:
        return rank_suggestions(phrase, collect_suggestions(db, phrase), limit)
