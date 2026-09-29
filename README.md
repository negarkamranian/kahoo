# Kahoo

Kahoo (کاهو) is a Persian RTL discovery layer for Iranian Instagram shops. Shoppers search by product or category, inspect merchant trust information in place, and continue to Instagram.

## Run

```bash
python3 server.py
```

- Marketplace: `http://127.0.0.1:4173`
- Saved items: `http://127.0.0.1:4173/saved.html`
- Admin analytics: `http://127.0.0.1:4173/admin.html`

Python and SQLite are the only runtime dependencies.

Refresh public Instagram biographies and profile counts:

```bash
python3 scripts/sync_instagram_profiles.py
# or only selected handles:
python3 scripts/sync_instagram_profiles.py @noghre_rose @sarinaland_com
```

Instagram may rate-limit anonymous public-page access. Failed profiles retain
their last sourced bio; product search descriptions are stored separately and
are never shown as Instagram biographies.

### Docker

```bash
docker build -t kahoo .
docker run --rm -p 4173:4173 kahoo
```

The image has no installed application dependencies and runs as an unprivileged user.

## Structure

```text
backend/
  server.py              HTTP API, search, Instagram import and analytics
data/
  schema.sql             SQLite schema
  kahoo.db               Local merchant, media and usage data
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

Runtime category reads come only from SQLite; `data/categories.sql` is the reproducible database seed.
