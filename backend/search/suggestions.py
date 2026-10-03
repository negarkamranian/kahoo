from backend.database import connect
from backend.search.normalization import normalize_search
from backend.search.ranking import term_match_strength


def search_suggestions(query, limit=8):
    phrase = normalize_search(query)[:80]
    if len(phrase) < 2:
        return []
    candidates = {}

    def add(value, label, kind, base=0):
        normalized = normalize_search(value)
        if not normalized:
            return
        strength = term_match_strength(phrase, normalized)
        if normalized == phrase:
            match = 100
        elif normalized.startswith(phrase):
            match = 85
        elif any(word.startswith(phrase) for word in normalized.split()):
            match = 75
        elif phrase in normalized:
            match = 65
        elif strength:
            match = 40 * strength
        else:
            return
        score = match + base
        previous = candidates.get(normalized)
        if not previous or score > previous[0]:
            candidates[normalized] = (score, {"value": value, "label": label, "type": kind})

    with connect() as db:
        for row in db.execute("SELECT name,handle FROM merchants"):
            add(row["name"], f"{row['name']} · {row['handle']}", "merchant", 8)
            add(row["handle"].lstrip("@"), f"{row['name']} · {row['handle']}", "merchant", 7)
        category_pattern = f"%{phrase}%"
        for row in db.execute(
            """SELECT label_fa FROM categories
          WHERE level>=2 AND (label_fa ILIKE %s OR label_en ILIKE %s)
          ORDER BY level,sort_order LIMIT 100""",
            (category_pattern, category_pattern),
        ):
            add(row["label_fa"], row["label_fa"], "category", 5)
        for row in db.execute(
            """SELECT term,MAX(weight) weight FROM merchant_search_terms
               WHERE normalized_term ILIKE %s GROUP BY term ORDER BY weight DESC LIMIT 100""",
            (f"{phrase}%",),
        ):
            add(row["term"], row["term"], "query", float(row["weight"]))
        for row in db.execute("""SELECT query,COUNT(*) uses FROM analytics_events
          WHERE event_type='search' AND query IS NOT NULL AND result_count>0
            AND created_at>=CURRENT_TIMESTAMP-INTERVAL '90 days'
          GROUP BY query ORDER BY uses DESC LIMIT 100"""):
            add(row["query"], row["query"], "popular", min(8, float(row["uses"])))
    return [
        item
        for _, item in sorted(
            candidates.values(), key=lambda pair: (pair[0], pair[1]["value"]), reverse=True
        )[: max(1, min(limit, 12))]
    ]
