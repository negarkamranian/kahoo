# Search and recommendation quality

The detailed live architecture, scoring flow, operations, and failure modes are
documented in [`search-core-flow.md`](search-core-flow.md). This file retains
the original benchmark rationale and product-level research notes.

Updated: 2 October 2026

## Benchmark findings

Kahoo follows a three-stage retrieval pattern: candidate generation, scoring,
and re-ranking. Google documents this as a common recommendation architecture
and recommends using re-ranking for quality, freshness, and diversity:

- https://developers.google.com/machine-learning/recommendation/overview/types
- https://developers.google.com/machine-learning/recommendation/dnn/re-ranking

PostgreSQL provides cover-density ranking while `pg_trgm` adds word-level
similarity for misspellings. Its documentation specifically recommends trigram
matching alongside full-text search for spelling recovery:

- https://www.postgresql.org/docs/current/functions-textsearch.html
- https://www.postgresql.org/docs/17/pgtrgm.html

pgvector recommends combining vectors with PostgreSQL full-text search and
using Reciprocal Rank Fusion (RRF) or a cross-encoder. RRF is suitable here
because lexical scores and cosine similarity do not share a meaningful scale:

- https://github.com/pgvector/pgvector#hybrid-search

Autocomplete and spell correction are separate jobs. Completion guides users
toward known entities and queries while they type; typo recovery belongs in
retrieval and ranking:

- https://www.elastic.co/guide/en/elasticsearch/reference/9.0/search-suggesters.html

## Implemented architecture

1. **Query understanding:** Unicode NFKC, Persian/Arabic character unification,
   digit conversion, half-space removal, stopword filtering, light plural
   variants, and curated commerce aliases.
2. **Candidate generation:** weighted-field prefix full-text retrieval,
   word-level trigram similarity, explicit post evidence, and optional
   multilingual BGE-M3 vectors.
3. **Fusion and scoring:** RRF combines lexical and vector ranks. Merchant name,
   category, description, biography, and reviewed metadata have explicit field
   weights, with a separate exact-phrase boost.
4. **Re-ranking:** a bounded quality tie-breaker considers audience, catalog
   activity, profile completeness, verification, and recent clicks. It cannot
   override a clearly more relevant result.
5. **Experience:** suggestions cover shops, categories, aliases, and popular
   queries. Results explain why they matched, and empty results offer recovery.
6. **Evaluation:** `data/search_benchmarks.json` is a reviewed Persian-commerce
   query set. `scripts/evaluate_search.py` reports Success@5, MRR@5, Recall@10,
   nDCG@10, zero-result rate, and latency percentiles.

## Operating loop

```bash
docker compose run --rm app python3 scripts/evaluate_search.py
docker compose run --rm app python3 scripts/reindex_search.py --batch-size 500 --all
```

Track zero-result rate, reformulation rate, Success@5, MRR@5,
search-to-profile rate, and profile-to-Instagram rate. Do not optimize only for
clicks: position bias and popularity feedback loops can bury smaller but more
relevant shops.

## Next data-dependent improvements

- Build judgments from anonymized query/result/click triples after enough real
  traffic exists; manually review them before training or tuning.
- Add session recommendations only after consent and retention rules are set.
- Add price and availability extraction after merchants can confirm those data.
- Consider a cross-encoder only when a larger reviewed set proves that its
  latency and cost improve relevance over RRF.
