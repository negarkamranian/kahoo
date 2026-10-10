# Search

Updated: 10 October 2026

The browser sends `q` and repeated `category` parameters. Category selection uses
OR semantics and includes descendants. Filters restrict lexical and vector
retrieval before candidate limits are applied.

## Indexing

Merchant documents contain identity, categories, biography, product description
and evidence-backed search terms. Post documents contain identity, categories
and the post caption. They do not repeat the merchant description: a general
shop claim should not masquerade as evidence for a particular post.

Changes invalidate the document's embedding. `search reindex --all` rebuilds the
index and embeds pending documents in batches. Retrieval only uses vectors from
the configured model.

## Retrieval and ranking

Hazm normalizes Persian letters, digits and punctuation. Query tokens exclude
stopwords and duplicates. Morphological matching compares Persian stems; prefix
matching is directional, and typo matching is conservative.

PostgreSQL full-text and trigram retrieval returns the best document per shop,
prioritizing query-token coverage. Dense retrieval searches 1024-dimensional
pgvector embeddings. Reciprocal rank fusion combines their rankings.

Each query concept contributes its strongest field score once. Broad categories
have less weight than shop identity and product descriptions. Description and
biography-derived metadata are excluded from the additional term score to avoid
counting the same content twice. Full query coverage is required for lexical
admission. Semantic matches can add paraphrases when embeddings are configured.
Complete lexical matches precede semantic-only candidates in the initial ranking.
Quality and click signals provide bounded tie-breakers.

When `RERANK_API_URL` is configured, a TEI cross-encoder scores the entire query
against up to 40 candidates. Candidate text includes the shop's identity,
description, biography and cached post captions. Final ordering follows the
cross-encoder score; results below `RERANK_MIN_SCORE` are removed. The cutoff is
an initial setting, not a measured probability of relevance. Tune it against
reviewed examples before judging production quality.

## Local models

`compose.search.yaml` runs Hugging Face multilingual E5 large and BGE reranker
v2 M3 on CPU. E5 requests use the model's required `query:` and `passage:` prefixes.
Models and downloads persist in the `kahoo-models` volume. No token is required.
The models require several GB of disk space and RAM, and CPU latency must be
measured on the deployment machine. Model-service errors propagate to the caller.

## Evaluation

`python -m backend search evaluate` reports nDCG@10, recall@10, MRR@5,
success@5, zero-result rate and p50/p95 latency against
`data/search_benchmarks.json`. Maintain specific product, attribute, shop-name,
spelling and paraphrase queries with reviewed relevance grades.

Unit tests cover misleading partial matches, repeated keywords, category
filter propagation, model-vector isolation and cross-encoder response contracts.
They verify behavior; they do not establish live model quality or latency.
