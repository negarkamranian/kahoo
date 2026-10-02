# Kahoo

Kahoo (کاهو) is a Persian RTL discovery layer for Iranian Instagram shops. Shoppers search by product or category, inspect merchant trust information in place, and continue to Instagram.

## Run

Kahoo now uses PostgreSQL with `pgvector`; the application does not write runtime data into Git or its container image.

```bash
cp .env.example .env
docker compose up --build
```

- Marketplace: `http://127.0.0.1:4173`
- Saved items: `http://127.0.0.1:4173/saved.html`
- Admin analytics: `http://127.0.0.1:4173/admin.html`

PostgreSQL data lives in the `kahoo-postgres` Docker volume. SQL migrations in `db/migrations` run automatically at startup.

### Import the previous SQLite data

Before starting the application for the first time, start PostgreSQL and import the existing local database:

```bash
docker compose up -d db
docker compose build app
docker compose run --rm \
  -v ./data/kahoo.db:/legacy/kahoo.db:ro \
  app python3 scripts/migrate_sqlite_to_postgres.py --source /legacy/kahoo.db
docker compose up app
```

The SQLite file is ignored by both Git and Docker after migration.

### Instagram synchronization

Set `META_IG_USER_ID` and `META_ACCESS_TOKEN` in `.env` to use Meta Business
Discovery. Without them, the public-embed reader scrapes the public Instagram
embed page as a best-effort fallback. Then run:

```bash
docker compose run --rm app python3 scripts/sync_instagram_profiles.py
```

To repair only missing or generated profile pictures without replacing post
galleries, run:

```bash
docker compose run --rm app python3 scripts/sync_profile_images.py
```

Pass one or more handles (for example `@rabostore`) to force-refresh specific
shops even when they already have a cached profile picture.

Business Discovery is the supported source for reading another public
professional account. It returns biography, profile picture,
follower/following counts, media counts, recent posts and carousel children.
It requires `instagram_basic`, `instagram_manage_insights` and
`pages_read_engagement`. Personal, private and age-gated accounts remain
unavailable, and Meta may omit downloadable media for licensed-audio videos or
Reels whose owner disabled downloads.

### Admin merchant management

The admin panel can add a shop from an Instagram username/profile URL and can
remove a shop together with its cached posts and search data. A removed catalog
shop is recorded in `merchant_exclusions`, so it will not return on restart.
Set a mutation token in `.env` before exposing the admin panel:

```dotenv
KAHOO_ADMIN_TOKEN=replace-with-a-long-random-value
```

Enter the same value in the admin panel when adding or removing a shop. Leaving
the variable empty keeps mutations unlocked for local development.

### Refresh the curated merchant catalog

The reviewed public-directory snapshot in `data/merchant_catalog.json` enriches
existing shops with sourced follower/post counts and adds new shops without
marking an external directory listing as Kahoo verification. On every run, the
import detects catalog shops that still have fewer than three cached post images
and fills them from their own account. Reapply it safely at any time (the import
is idempotent). Rebuild the app image first after pulling script changes:

```bash
docker compose build app
docker compose run --rm app python3 scripts/seed_merchants.py
docker compose up -d app
```

Large expansions are added to PostgreSQL immediately, while Instagram media is
synchronized in resumable batches of 25. Run the seed command repeatedly to
finish later batches, or choose a different batch size:

```bash
docker compose run --rm app python3 scripts/seed_merchants.py --media-limit 50
```

Use `--skip-media` for a fast catalog-only import, `--media-limit 0` for one
long-running full sync, or `--repair-avatars` for a separate retry pass over
missing/generated profile pictures.

The profiles shared in `shops.txt` are stored in
`data/merchant_catalog_shared.json`. To rebuild that catalog after changing the
list, run:

```bash
python3 scripts/build_shared_merchants.py shops.txt --output data/merchant_catalog_shared.json
```

Then rebuild the app image and run the seed command above. The catalog import
adds every shop immediately; subsequent resumable media batches fill its real
profile picture, biography, metrics, posts, and carousel children.

Live Instagram synchronization takes precedence over snapshot metrics on its
next successful refresh. Every metric stores its source URL and timestamp.

To add one shop directly from its public Instagram identifier, run:

```bash
docker compose run --rm app python3 scripts/add_merchant.py @shop_username
```

The identifier may also be a profile URL. The command is idempotent and stores
the merchant, current profile picture, metrics, recent posts, and carousel
children. It infers the GPC category from the public profile and captions; for
an ambiguous account, provide it explicitly, for example
`--category 66010100`. Optional `--name`, `--description`, and `--city` flags
can override the public defaults.

To replace any earlier generated gallery entries, collect the shops' own posts,
and cache the returned media in PostgreSQL:

```bash
docker compose run --rm app python3 scripts/backfill_gallery_images.py
```

The command tries Meta Business Discovery first when credentials are configured,
otherwise it reads each public Instagram embed. It stores only successfully
downloaded shop media in `merchant_posts.image_blob`; it does not create gallery
placeholders. The JSON report lists failures and image counts per handle.

### Search quality

Search includes Persian normalization and morphology, commerce synonyms,
weighted full-text and trigram retrieval, post-level evidence, optional BGE-M3
vector retrieval with RRF, coverage/proximity scoring, bounded behavioral
signals, autocomplete, explanations, and empty-result recovery. The complete
flow and runbook are in `docs/search-core-flow.md`; research notes remain in
`docs/search-quality.md`.

Run the reviewed Persian-commerce relevance benchmark with:

```bash
docker compose run --rm app python3 scripts/evaluate_search.py
```

Configure an OpenAI-compatible embedding endpoint that returns 1024-dimensional
BGE-M3 vectors, then index changed documents:

```bash
docker compose run --rm app python3 scripts/reindex_search.py --batch-size 500 --all
```

If no embedding endpoint is configured, Persian-normalized lexical, alias and category search continues to work.

## Structure

```text
backend/
  database.py            PostgreSQL connection and migration runner
  instagram.py           Meta Business Discovery client
  search.py              Search documents and embedding retrieval
  server.py              HTTP API, hybrid ranking and analytics
db/migrations/          Versioned PostgreSQL schema
data/
  categories.sql         Reproducible GS1 category seed
  merchant_catalog.json Versioned merchant enrichment snapshot
  merchant_catalog_expansion_*.json High-audience expansion shards
  merchant_catalog_shared.json User-submitted Instagram shops
docs/
  product-research.md
  market-benchmarks.md
  archive/                Earlier challenge notes
public/
  index.html
  saved.html
  admin.html
  assets/
    css/                  Marketplace, theme and admin styles
    js/                   Catalog and admin behavior
server.py                 Development entrypoint
```

## Current product

- Hierarchical, Iran-relevant GS1 category tree
- Persian-normalized merchant search
- Real merchant handles, cached profile photos and stored post images
- Three-image, low-distraction rotating preview
- In-page merchant profile and trust modal
- Locally persisted saved merchants and posts with an account view
- Direct Instagram handoff from merchant buttons and posts
- Instagram OAuth-shaped onboarding prototype
- Anonymous usage analytics and RTL admin dashboard
- Responsive, keyboard-accessible interface with reduced-motion support

## API

```text
GET  /api/categories
GET  /api/search/suggestions?q={query}
GET  /api/merchants?category={gpc_code}&q={query}
GET  /api/merchants/{id}
GET  /api/media/{id}
GET  /api/avatars/{id}
GET  /api/admin/metrics?days=7|30|90
POST /api/analytics/event
POST /api/login/request
POST /api/login/verify
POST /api/merchants/import-demo
```

The production onboarding path is Instagram OAuth → profile/media import → suggested category → merchant confirmation. Public-profile extraction is only a prototype fallback; authenticated synchronization should be the production source of truth.

## Category data

The database contains the four GS1 GPC levels—segment, family, class and brick—filtered for Kahoo's Iranian marketplace scope. The generated seed currently contains 6,031 categories from the May 2026 schema. Tobacco/cannabis, postmortem products, sexual products, weapons, gambling, alcohol-related branches and other excluded areas are defined in `data/gpc_policy.json`.

To rebuild the seed from the official current and Persian GS1 publications:

```bash
python3 scripts/build_gpc_categories.py --download
```

Runtime category reads come only from PostgreSQL; `data/categories.sql` is the reproducible database seed.
