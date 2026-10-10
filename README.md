# Kahoo · کاهو

A Persian marketplace for discovering Instagram shops and their products.
Search, filter by several categories, save shops or posts, and open them on Instagram.

## Run

```bash
cp .env.example .env
docker compose --env-file .env.example --env-file .env up --build -d
```

Open **http://localhost:4173**. Admin: `/admin.html`. Saved items: `/saved.html`.

### Instagram product enrichment

Every imported Instagram post is treated as one candidate product (a carousel is one
product, not one product per photograph). Ingestion saves its caption and all cached
images and queues it in the same transaction. A background worker classifies the primary
advertised product using the Shopify product taxonomy, then extracts only that category's
attributes. Non-product posts are marked separately. Posts containing several unrelated
products currently produce a classification for the primary product, not separate listings.

Configure a vision model that supports image inputs and JSON mode in `.env`:

```dotenv
PRODUCT_VISION_API_URL=https://your-provider.example/v1/chat/completions
PRODUCT_VISION_API_KEY=your-provider-key
PRODUCT_VISION_MODEL=your-vision-model
PRODUCT_VISION_TIMEOUT=90
PRODUCT_VISION_MAX_IMAGES=8
```

The endpoint uses the [OpenAI-compatible Chat Completions image and JSON request format](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create).
The URL must include `/v1/chat/completions`; the key may be empty for a local endpoint.
The caption and cached image bytes are sent to the configured provider. At most the configured
number of images are analyzed, in carousel order; the admin result records any truncation.
Leaving the URL or model empty keeps new products queued without making model requests.
Never put real API credentials in `.env.example` or the admin browser.

Rebuild the server to apply the migration and start the worker:

```bash
docker compose --env-file .env.example --env-file .env up --build -d app
```

Open **Admin → ارزیابی محصولات**. If `KAHOO_ADMIN_TOKEN` is configured, enter it in
the existing admin key field. Expand a product to compare the original caption and
photographs against the taxonomy category, each attribute, its evidence and confidence,
and the model/version provenance. Missing facts stay explicitly unknown; confidence is
the model's estimate and is not calibrated. Approve or reject a result with a review note,
inspect its run history, or request reprocessing. Search, processing/review filters and
pagination help assess the backlog. Review decisions do not automatically publish new
attributes to the public catalog.

The worker backfills existing post collections on startup. The admin's backfill button
or CLI can also enqueue them. Products keep independent image snapshots so later refreshes
of the merchant's recent Instagram gallery do not delete the evidence or assessment.
This retains an additional copy of product images in PostgreSQL. Identical captions/image
bytes preserve completed results and review decisions; changed evidence clears the previous
assessment and queues a new run. Old runs remain in `product_enrichment_runs`.

Jobs use committed leases and `FOR UPDATE SKIP LOCKED`, so multiple workers can process
different products. Model calls do not hold ingestion transactions open. Failed jobs retry
up to three attempts with backoff, and abandoned leases can be recovered after 30 minutes.
A result from an old lease or old evidence cannot overwrite the current product.

```bash
# Queue older post collections without calling a model.
python -m backend products enqueue
# Process at most 50 jobs once (requires the configured vision endpoint).
python -m backend products worker --once --limit 50
# Optional separate worker; the HTTP server already starts one when configured.
python -m backend products worker --poll-seconds 5
```

All `/api/admin/products` endpoints, including images, history, reviews and retries,
use the configured admin token. Classification/value IDs are validated against the
offline taxonomy; unsupported categories, attributes, values and unsupported filled
attributes fail the job rather than being saved as valid product facts.
API docs: `/docs`.

For a new database, import the catalog and fetch images:

```bash
docker compose run --rm app python -m backend catalog import
docker compose run --rm app python -m backend media sync --only-missing --limit 25
```

For these and all commands below, pass `--env-file .env.example --env-file .env`
to `docker compose`. Startup applies migrations; catalog imports are explicit.

## Search

Search uses Persian normalization, full-text and typo matching, query coverage,
and phrase ranking. Complete query matches precede partial matches. Selecting
several categories includes shops from **any** selected category and its children.

Merchant descriptions are short product summaries based on recorded evidence.
Search terms retain specific products, brands and attributes. Apply the edited batch:

```bash
make db-backup
docker compose run --rm app python -m backend search enrich-file data/merchant_enrichment.json
docker compose run --rm app python -m backend search reindex --all
docker compose run --rm app python -m backend search evaluate
```

### Free local AI search

The optional setup runs Hugging Face **multilingual E5 large** embeddings and
**BGE reranker v2 M3** locally. No account, token or inference bill is needed.
The first start downloads several GB of model files; both models need several GB
of available RAM. CPU inference is slower than GPU inference.

```bash
docker compose --env-file .env.example --env-file .env \
  -f compose.yaml -f compose.search.yaml up --build -d
```

Wait for both model services to finish loading (`docker compose -f compose.yaml
-f compose.search.yaml logs embeddings reranker`), then import the descriptions,
index and evaluate using the same two Compose files:

```bash
docker compose --env-file .env.example --env-file .env \
  -f compose.yaml -f compose.search.yaml run --rm app \
  python -m backend search enrich-file data/merchant_enrichment.json

docker compose --env-file .env.example --env-file .env \
  -f compose.yaml -f compose.search.yaml run --rm app \
  python -m backend search reindex --all

docker compose --env-file .env.example --env-file .env \
  -f compose.yaml -f compose.search.yaml run --rm app \
  python -m backend search evaluate
```

Embeddings retrieve related wording; the cross-encoder evaluates the complete
query against up to 40 candidates. `RERANK_MIN_SCORE` controls the relevance cutoff
(default `0.2`; tune against the benchmark). Configured model failures are surfaced.
Reindex after changing embedding models. Only vectors from the active model are searched.

For another embedding service, set `EMBEDDING_API_URL`, `EMBEDDING_API_KEY` and
`EMBEDDING_MODEL` in `.env`. It must provide an OpenAI-compatible endpoint and
1024-dimensional vectors. A TEI reranker can be set through `RERANK_API_URL`.

## Useful commands

Run commands with `python -m backend`; every command supports `--help`.

| Command | Purpose |
| --- | --- |
| `merchants add @handle --category CODE` | Add or refresh a shop. |
| `merchants list` | List stored shops. |
| `media sync --only-missing` | Refresh missing profile images and posts. |
| `search reindex --all` | Rebuild search documents and embeddings. |
| `search evaluate` | Measure ranking quality and latency. |
| `make db-backup` | Back up PostgreSQL to `backups/`. |

Set `KAHOO_ADMIN_TOKEN` before exposing the admin panel. Phone login is a demo:
it does not verify phone ownership. Saves belong to the browser's server session.
PostgreSQL data persists in a Docker volume; `docker compose down -v` deletes it.

## Product taxonomy and attributes

The complete [Shopify 2026-08 product taxonomy](https://shopify.github.io/product-taxonomy/releases/2026-08/)
is stored in `data/shopify/2026-08/`: **14,606 categories**, **8,240 attributes**
and **74,820 allowed values**. It works offline. `upstream-taxonomy.json.gz`
preserves Shopify's original export, including its additional fields;
`taxonomy.json.gz` contains the application index. `metadata.json` records the
pinned upstream commit, download URL and SHA-256. Shopify's MIT license is included.

Use these endpoints for product classification (also documented at `/docs`):

| Endpoint | Purpose |
| --- | --- |
| `/api/taxonomy` | Release metadata and counts. |
| `/api/taxonomy/tree` | Complete category tree, including all eight levels. |
| `/api/taxonomy/categories?q=shoes&limit=100&offset=0` | Search and paginate categories. |
| `/api/taxonomy/categories?parent=aa-1` | Direct children; `parent=root` lists roots. |
| `/api/taxonomy/categories/aa-1` | Category details and applicable attribute references. |
| `/api/taxonomy/categories/aa-1/attributes` | Category-specific attributes and their allowed values. |
| `/api/taxonomy/attributes?q=color` | Search and paginate attribute definitions. |
| `/api/taxonomy/attributes/color` | An attribute and its allowed values, by handle. |

Category codes such as `aa-1` retain Shopify's IDs and zero-based levels.
Extended attribute handles (such as `liner-features`) resolve to the underlying
attribute's allowed values while retaining their category-specific name and description.
Shopify's source labels are English. Existing Persian GS1 shop classifications
and shop browsing remain in `/api/categories`; this import adds the product taxonomy
without guessing new shop assignments or translations.

Refresh the pinned release, or rebuild it from the checked-in export without network access:

```bash
python -m backend catalog sync-shopify
python -m backend catalog sync-shopify \
  --source data/shopify/2026-08/upstream-taxonomy.json.gz \
  --license data/shopify/2026-08/LICENSE
```

These commands need no database. Restart the server after refreshing taxonomy data.

## Develop

Python 3.13 and Node.js 22.13+.

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
npm ci
make check
```

`backend/` contains FastAPI, services and search. `public/` contains the UI.
`data/` holds catalogs and research. `db/migrations/` holds database migrations.
`tests/` contains Python and browser tests. Search notes are in
[system_design_documents/](system_design_documents/).
