# Kahoo

Kahoo (کاهو) is a Persian RTL discovery app for Iranian Instagram shops.
Shoppers search stored profiles and posts, save items in PostgreSQL, and continue to Instagram.

## Start the app

```bash
cp .env.example .env
docker compose --env-file .env.example --env-file .env up --build
```

Open the [marketplace](http://127.0.0.1:4173), [saved items](http://127.0.0.1:4173/saved.html),
or [admin panel](http://127.0.0.1:4173/admin.html).

API documentation is available through [Swagger UI](http://127.0.0.1:4173/docs),
[ReDoc](http://127.0.0.1:4173/redoc), and the [OpenAPI schema](http://127.0.0.1:4173/openapi.json).

Startup applies PostgreSQL migrations and seeds categories. Merchant data stays
in the `kahoo-postgres` Docker volume. To populate a new database and fetch media:

```bash
docker compose --env-file .env.example --env-file .env run --rm app python3 -m backend catalog import
docker compose --env-file .env.example --env-file .env run --rm app python3 -m backend media sync --only-missing --limit 25
```

Catalog import is explicit; normal startup does not import snapshots or contact Instagram.

## Database ownership and upgrades

PostgreSQL holds the catalog, cached images, search documents, analytics, users,
sessions, login challenges, and saved shops/posts. Legacy browser storage is used
only to import old saved collections; a successful server acknowledgement removes
the corresponding browser records. Failed, invalid, or missing references remain
in the browser and the saved page offers a retry. Open the updated app on its
original URL so it can read that browser origin's existing saves.
Session bootstrap and imports coordinate across tabs with Web Locks. Browsers
without that API retain the old browser copies even after importing them, so
concurrent first visits cannot discard the only accessible copy.

Migrations 014 and 015 add accounts and saved collections to the existing database.
They retain catalog and analytics rows. Session cookies identify ownership; the
database stores a hash of the private cookie token. The public analytics session
ID grants no access to saved items. Saved posts use stable collection keys and a
canonical image snapshot so gallery refreshes do not erase them.

Back up before applying the update, then rebuild the app:

```bash
make db-backup
docker compose --env-file .env.example --env-file .env up --build -d app
```

Startup applies outstanding numbered migrations and the category seed in one
transaction, with an advisory lock to serialize concurrent startup/CLI work.
Keep applied migration files unchanged; add a new numbered SQL file for each
schema change. Inspect applied versions with:

```bash
docker compose --env-file .env.example --env-file .env exec -T db \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT version, applied_at FROM schema_migrations ORDER BY version"'
```

Use admin/CLI operations for catalog edits and run snapshot imports deliberately.
Do not run `docker compose down -v` against data you want to retain.

Run `make db-backup` daily and before migrations or bulk imports. It creates a
private, validated custom-format archive under `backups/`, ignored by Git.
Copy completed archives to a separate storage location. Regularly verify a
restore into a fresh database:

```bash
make db-restore RESTORE_DB=kahoo_restore_check BACKUP_FILE=backups/ARCHIVE.dump
```

Restore refuses the active database and existing names; it does not change the
app's connection. Check the restored data before any intentional cutover.

Phone login remains an explicitly unverified demo: any five digits complete a
short-lived challenge bound to the current cookie session. It updates that
guest's persisted user row, never looks up another owner by phone, and keeps
`phone_verified=false`. Old browser login labels are discarded because they
were not verified identities. Access persists through the cookie on this browser;
cross-device sign-in requires an actual SMS verification provider. The admin
token stays in environment configuration and the current input, rather than
being stored by the browser.

## Project structure

```text
backend/
  __main__.py          Entry point: python -m backend
  cli/                 Command-line interface
    __init__.py        Command parsing, validation, and dispatch
    catalog.py         Catalog import and category seed generation
    merchants.py       Merchant management commands
    media.py           Media maintenance commands
    search.py          Search indexing, evaluation, and enrichment commands
  server/              FastAPI routes, static files, and Uvicorn lifecycle
  services/            Shared application logic
    catalog.py         Snapshot validation and import
    merchants.py       Merchant reads, imports, and removal
    profiles.py        Profile synchronization and media completeness
    media.py           Image downloads, caching, and persistence
    categories.py      Category tree
    analytics.py       Events and admin metrics
    accounts.py        Cookie sessions and persistent demo login challenges
    saved.py           Private saved collections, imports, and media snapshots
  search/              Normalization, indexing, retrieval, ranking, enrichment
  database.py          PostgreSQL connections and shared database setup
  models/              Typed contracts, grouped by domain
    common.py          Shared types and model base
    merchants.py       Merchant inputs, views, and import reports
    media.py           Normalized profiles, media, galleries, and sync reports
    categories.py      Category tree, GS1 publications, and generation policy
    catalog.py         Catalog snapshots and import reports
    analytics.py       Events and admin metrics
    auth.py            Accounts, sessions, and login requests
    saved.py           Saved collection views and import references
    search.py          Search, enrichment, benchmarks, and command reports
    instagram/         Instagram wire schemas: common, embed, and Meta
  config.py            Environment loading and shared typed settings
  instagram/           Instagram profile sources, embed parsing, and URL helpers
    service.py         Select the configured profile source
    embed.py           Public embed parsing
    meta.py            Meta Business Discovery requests
    urls.py            Canonical Instagram URLs
public/                HTML pages and browser CSS/JavaScript
  assets/css/
  assets/js/
data/                  Reviewed merchant catalogs, category seed, search benchmarks
db/migrations/         Ordered, versioned PostgreSQL schema changes
tests/                 Python tests and browser-module tests
docs/                  Search details, product research, and source notes
  archive/             Historical planning notes
```

The request flow is **browser → FastAPI routes → services/search → PostgreSQL**.
CLI commands call the same services. Both server startup and database-backed
commands use `database.initialize_database()` for schema and category setup.
Merchant imports and profile updates refresh search metadata and documents.

Start with `backend/server/routes.py` for routes, `backend/cli/__init__.py` for commands,
and `backend/search/service.py` for search orchestration. Shared application
logic belongs in `services/`; request and command handling stays at the edges.
FastAPI validates request bodies into Pydantic models and serializes returned models
and lists directly. CLI and Instagram adapters parse external JSON into models.
Services pass those models using attributes and return structured models.
Required fields fail validation; do not guess alternate
keys, identities, or content. Defaults belong in the owning model, and derived
values (such as post collection keys and cover images) have one definition.
Import contracts directly from their owning `backend.models` module; package
initializers do not re-export models.

Instagram wire contracts live in `backend/models/instagram/`. Embed posts require
`shortcode_media`, `__typename`, and `display_url`; Meta posts use `media_type`
to select image, video-thumbnail, or carousel fields. Media IDs are required.
An embed response must contain one media context with its profile and post list.
Migration 013 fills legacy collection keys once and requires them on future inserts.
Image downloads determine their MIME type from supported image signatures.

Search benchmarks use only `relevance` maps (grades 1–3); `expected_handles` is no
longer supported. Category generation validates GS1 publications and requires a
Persian label for every included category, from the translation publication plus
explicit policy overrides. Missing labels stop generation before writing output.
Analytics requests take the session ID only from `X-Kahoo-Session`.

## Common operations

Use `python3 -m backend` for every command. In Docker, prefix it with
`docker compose --env-file .env.example --env-file .env run --rm app`. Every command supports `--help`. Instagram handles
must already be in lowercase `@username` format.

| Command | Purpose |
| --- | --- |
| `serve [--host HOST] [--port PORT]` | Start the HTTP server. |
| `db migrate` | Apply schema migrations and seed categories. |
| `merchants list [--query TEXT]` | Inspect stored merchants. |
| `merchants add IDENTIFIER --category CODE` | Add or refresh an Instagram profile. |
| `merchants import-file PATH --category CODE` | Import @username handles from a text file. |
| `merchants remove ID` | Delete a merchant and exclude it from future catalog imports. |
| `catalog import [PATH ...]` | Import JSON snapshots; no paths means the checked-in catalogs. |
| `catalog build-categories --current PATH --persian PATH [--download]` | Rebuild the GS1 category seed using `data/gpc_policy.json`. |
| `media status [HANDLE ...]` | Report missing avatars and incomplete galleries. |
| `media sync [HANDLE ...] [--only-missing] [--limit N]` | Refresh profiles and galleries. |
| `media cache [HANDLE ...]` | Cache stored post URLs without refreshing profiles. |
| `search reindex [--batch-size N] [--all]` | Refresh metadata, search documents, and optional embeddings. |
| `search evaluate [--benchmark PATH]` | Run the reviewed relevance benchmark. |
| `search enrich ID PATH` | Import a sourced JSON description and search terms. |
| `search enrich-file PATH` | Atomically import a researched batch matched by Instagram handle. |

Instagram imports use the fetched profile name and biography as the merchant name
and description. Manual name/description overrides are not supported. Missing or
blank profile names fail the import; an empty biography stays empty.

New merchants require an explicit GPC category; existing merchants retain theirs
when `--category` is omitted. Imports preserve snapshot provenance, newer live
metrics, and LLM descriptions. Use separate handle files for different categories.

Catalog snapshots may omit fields supplied by the seed. Imports validate the
merged merchant's required name before writing to the database; they do not invent
missing names. Duplicate handles within or across snapshot files are rejected.

For media sync, `--avatars-only` preserves galleries and `--limit 0` processes all
matches. Status and sync use `--minimum-post-images` (default: 3) for completeness.
Failed downloads preserve saved media. Commands print their result models on success. Runtime
errors stop the command with a traceback and a nonzero exit status; batches stop
at the first failure. Earlier completed profiles remain committed.

Unexpected HTTP request errors propagate to Uvicorn, which logs a traceback
and returns HTTP 500. Other requests continue running. Configured embedding
services must succeed; search does not silently fall back after an embedding error.

The former `python3 -m scripts` entry point is replaced by `python3 -m backend`.
The legacy SQLite importer has been removed; the app uses PostgreSQL.

## Configuration

All configuration defaults live in `.env.example`. Local runs load it automatically,
with `.env` and existing environment variables taking precedence. Docker Compose
loads both files through the `--env-file` arguments shown above. `backend/config.py` loads and validates the settings once at startup. Other modules
use its shared `settings` object; environment changes require a restart. Server CLI
flags override the configured host and port directly.

Missing profile pictures stay empty; no initials or generated avatars are used.

- `DATABASE_URL`: PostgreSQL connection for local runs; Compose supplies its own.
- `KAHOO_HOST` / `KAHOO_PORT`: server address; CLI flags override these.
- `KAHOO_ADMIN_TOKEN`: token required for admin mutations when configured.
  An empty token leaves mutations unlocked for development.
- `META_IG_USER_ID` / `META_ACCESS_TOKEN`: enable Meta Business Discovery.
  Without them, profile reads use the public Instagram embed reader.
- `EMBEDDING_API_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL`: optional
  OpenAI-compatible embedding endpoint with 1024-dimensional vectors.

Search works without embeddings using stored content, Hazm normalization and stemming,
full-text search, and trigram matching. Enrichment JSON requires `description`,
`terms` (a list), `model`, and `source_url`; `confidence` is optional.
Search adds lowercase matching, ASCII digits, and punctuation/half-space separators
to Hazm's output. After upgrading from the handwritten normalizer, rebuild stored
search metadata and documents with `python3 -m backend search reindex`.
See [the search flow](docs/search-core-flow.md) for indexing and ranking details.

### Shop research and enrichment

`data/merchant_enrichment.json` contains researched Persian text for the 34 shops
in the active catalog. Each record includes natural search terms, SEO title and
meta description, evidence URLs, access status, confidence, and explicit research
limitations. The text combines observed cached post imagery, available profile
information, official sites, and indexed public pages. Unavailable biographies
and captions are marked as gaps; prices, stock, authenticity, and delivery claims
are not inferred from images or directory scores.

After backing up and rebuilding the app, apply the reviewed batch:

```bash
docker compose --env-file .env.example --env-file .env run --rm app \
  python3 -m backend search enrich-file data/merchant_enrichment.json
```

`make shop-enrich` performs the backup, rebuild, and import in that order,
stopping if any step fails.

The command resolves canonical handles against existing merchants. Unknown or
duplicate handles stop the import. It commits descriptions, generated terms,
source provenance, and search indexing in one transaction, leaving names and
biographies intact. Migration 016 retains the previous description and provenance
plus the complete research payload in `merchant_enrichment_history`. Reapplying
the same batch reports unchanged shops without duplicating history.
Research older than an existing enrichment is rejected before any shop changes.

Descriptions and terms feed the existing search documents and suggestions.
Changed document content invalidates old embeddings; run `search reindex --all`
when an embedding provider is configured. SEO fields are retained in the research
payload for future page metadata. New research should have a fresh UTC
`researched_at` timestamp and cite only evidence actually checked.

## Development and checks

Use Python 3.13 (also used by Docker) and Node.js 22.13+. Runtime dependencies
are in `requirements.txt`; development tools are in `requirements-dev.txt` and
`package.json` (with a checked-in npm lockfile).

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci
make check
pre-commit install
python -m backend --help
```

Make targets use `.venv/bin/python` by default, so they work without activating
the virtual environment. Use `PYTHON=python` to select another interpreter explicitly.

`make check` runs Ruff lint/import/complexity checks, Pylint, ESLint, Ruff and
Prettier formatting checks, and Python and JavaScript tests. `make format` applies
formatting and import sorting. `pre-commit run --all-files` also checks YAML/TOML,
trailing whitespace, and final newlines. CI runs the same checks on pushes and PRs.

Keep each function focused on one responsibility. Python complexity is limited to
8, Pylint allows at most 30 statements and 6 branches, and browser functions are
limited to 40 nonblank lines and complexity 8. Search scoring rules and explanation
priorities are named tables; adjust them in one place.

Tests and command help run without database or Instagram credentials.
Serving the app, database commands, and live search evaluation require PostgreSQL.
