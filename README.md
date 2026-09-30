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

Set `META_IG_USER_ID` and `META_ACCESS_TOKEN` in `.env` to use Meta Business Discovery. Without them, the prototype public-embed reader remains a best-effort fallback. Then run:

```bash
docker compose run --rm app python3 scripts/sync_instagram_profiles.py
```

Business Discovery supports public professional accounts and returns biography, profile picture, follower/following counts, media counts, recent posts and carousel children. Personal, private and age-gated accounts remain unavailable.

### Semantic search

Configure an OpenAI-compatible embedding endpoint that returns 1024-dimensional BGE-M3 vectors, then index changed documents:

```bash
docker compose run --rm app python3 scripts/reindex_search.py
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
